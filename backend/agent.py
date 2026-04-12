"""
Agent Fiscal — Orchestration multi-étapes.

Pipeline :
  Étape 1 — INGESTION    : Doc brut -> Extraction structurée universelle -> RAG local extractions -> Profil JSON
  Étape 2 — VALIDATION   : Profil analysé -> "il me manque X, Y, Z" -> questions ciblées
  Étape 3 — CALCUL       : RAG fiscal + profil JSON (seule source de vérité) -> cases 2042
  Étape 4 — VÉRIFICATION : Cross-check cohérence -> rapport final

Les PDFs ne sont jamais relus après l'étape 1.
Le profil JSON est la SEULE source de vérité pour le calcul.
"""
import json
import re
from pathlib import Path

from ollama_client import query_llm
from document_parser import DocumentParser
from fiscal_engine import FiscalEngine
from report_generator import ReportGenerator
from rag import FiscalRAG
from fiscal_profile import FiscalProfile
from session_store import SessionStore
from extraction_store import ExtractionStore
from extractors import extract_structured

SYSTEM_PROMPT = (
    "Tu es un assistant fiscal expert en déclaration d'impôts française. "
    "Tu travailles UNIQUEMENT avec le profil fiscal JSON fourni — jamais avec des documents bruts. "
    "Tu réponds en JSON quand demandé. Tu ne devines pas les informations manquantes."
)

# États du pipeline
STATE_WELCOME = "welcome"
STATE_INGESTION = "ingestion"
STATE_VALIDATION = "validation"
STATE_CALCUL = "calcul"
STATE_VERIFICATION = "verification"
STATE_DONE = "done"


class AgentFiscal:
    def __init__(self, document_parser: DocumentParser, fiscal_engine: FiscalEngine,
                 report_generator: ReportGenerator, session_id: str = ""):
        self.parser = document_parser
        self.engine = fiscal_engine
        self.reporter = report_generator
        self.rag = FiscalRAG()
        self.session_id = session_id

        # Mémoire persistante
        self.store = SessionStore(session_id) if session_id else None
        self.profile = FiscalProfile(session_id) if session_id else None
        self.extractions = ExtractionStore(session_id) if session_id else None

        # Callbacks pour envoyer des messages en temps reel (set par app.py)
        self.on_progress = None  # async def(msg: dict) -> None — progression ingestion
        self.on_send = None      # async def(msg: dict) -> None — messages intermediaires

        # État courant
        self._restore_state()

    def _restore_state(self):
        """Restaure l'état depuis la mémoire persistante."""
        if self.store and not self.store.is_new():
            self.state = self.store.get("state", STATE_WELCOME)
            self.documents_path = self.store.get("documents_path", "")
            self.conversation_history = self.store.get_history()
            self.pending_questions = self.store.get("pending_questions", [])
            self.current_question_index = self.store.get("current_question_index", 0)
            print(f"[SESSION] Restaurée : état={self.state}, profil complétude={self.profile.get_completeness():.0%}")
        else:
            self.state = STATE_WELCOME
            self.documents_path = ""
            self.conversation_history = []
            self.pending_questions = []
            self.current_question_index = 0
            if self.store:
                self.store.init_session()

    def _persist(self):
        """Sauvegarde l'état courant."""
        if not self.store:
            return
        self.store.set_many({
            "state": self.state,
            "documents_path": self.documents_path,
            "pending_questions": self.pending_questions,
            "current_question_index": self.current_question_index,
        })

    # ==================================================================
    # Point d'entrée principal
    # ==================================================================

    def get_welcome_message(self) -> str:
        if self.state != STATE_WELCOME and self.profile:
            return self._get_resume_message()
        return (
            "Bonjour ! Je suis votre assistant fiscal local.\n\n"
            "**Toutes vos données restent sur votre ordinateur.**\n\n"
            "Pour commencer, indiquez le **chemin du dossier** contenant vos documents fiscaux.\n\n"
            "Exemple : `C:\\Users\\MonNom\\Documents\\Impots2025`"
        )

    async def process_message(self, user_message: str) -> list[dict]:
        self.conversation_history.append({"role": "user", "content": user_message})
        if self.store:
            self.store.add_message("user", user_message)

        responses = []

        if self.state == STATE_WELCOME:
            responses = await self._step_start(user_message)
        elif self.state == STATE_INGESTION:
            # Reprise d'ingestion interrompue : l'utilisateur tape n'importe quoi pour relancer
            responses = await self._resume_ingestion()
        elif self.state == STATE_VALIDATION:
            responses = await self._step_validation_answer(user_message)
        elif self.state == STATE_CALCUL:
            responses = await self._step_calcul()
        elif self.state == STATE_VERIFICATION:
            responses = await self._step_verification()
        elif self.state == STATE_DONE:
            responses = [self._msg(
                "Le rapport a déjà été généré. Consultez le dossier `output/`. "
                "Rechargez la page pour une nouvelle déclaration."
            )]

        for r in responses:
            if r.get("type") == "assistant":
                self.conversation_history.append({"role": "assistant", "content": r["content"]})
                if self.store:
                    self.store.add_message("assistant", r["content"])

        self._persist()
        return responses

    # ==================================================================
    # Étape 0 : Démarrage — choix du dossier
    # ==================================================================

    async def _step_start(self, folder_path: str) -> list[dict]:
        folder_path = folder_path.strip().strip('"').strip("'")
        folder = Path(folder_path)

        if not folder.exists():
            return [self._msg(f"Le dossier `{folder_path}` n'existe pas. Vérifiez le chemin.")]
        if not folder.is_dir():
            return [self._msg(f"`{folder_path}` n'est pas un dossier.")]

        self.documents_path = str(folder)

        # Scanner les fichiers
        supported_ext = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".xlsx", ".xls", ".csv", ".docx", ".txt"}
        files = [f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in supported_ext]

        if not files:
            return [self._msg(f"Aucun document exploitable dans `{folder_path}`.\n\nFormats : PDF, PNG, JPG, XLSX, CSV, DOCX, TXT.")]

        file_list = "\n".join(f"  - `{f.relative_to(folder)}`" for f in files[:30])
        if len(files) > 30:
            file_list += f"\n  - ... et {len(files) - 30} autre(s)"
        nb_total = len(files)

        self.state = STATE_INGESTION
        self._persist()

        # Envoyer la liste des fichiers IMMEDIATEMENT (avant l'ingestion)
        await self._send_now(
            f"**{nb_total} document(s)** trouves :\n\n{file_list}\n\n"
            "Je vais analyser chaque document un par un pour construire votre profil fiscal..."
        )

        # L'ingestion envoie la progression en temps reel via on_progress
        # et retourne le resume final + les messages de validation
        return await self._step_ingestion(files, folder)

    async def _resume_ingestion(self) -> list[dict]:
        """Reprend une ingestion interrompue (crash, kill, fermeture navigateur)."""
        if not self.documents_path:
            self.state = STATE_WELCOME
            self._persist()
            return [self._msg("Session corrompue. Veuillez indiquer le chemin du dossier de documents.")]

        folder = Path(self.documents_path)
        if not folder.exists():
            self.state = STATE_WELCOME
            self._persist()
            return [self._msg(f"Le dossier `{self.documents_path}` n'existe plus. Indiquez un nouveau chemin.")]

        supported_ext = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".xlsx", ".xls", ".csv", ".docx", ".txt"}
        files = [f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in supported_ext]

        already_done = {e.get("doc_id") for e in self.extractions.get_all()} if self.extractions else set()
        remaining = len(files) - len(already_done)

        await self._send_now(
            f"**Reprise de l'analyse** : {len(already_done)} document(s) deja traite(s), "
            f"{remaining} restant(s) sur {len(files)}.\n\n"
            "L'analyse reprend..."
        )

        return await self._step_ingestion(files, folder)

    # ==================================================================
    # Etape 1 : INGESTION -- extraction structuree -> RAG local -> profil
    # ==================================================================

    async def _send_progress(self, msg: dict):
        """Envoie un message de progression en temps reel via le WebSocket."""
        if self.on_progress:
            try:
                await self.on_progress(msg)
            except Exception:
                pass

    async def _send_now(self, content: str, msg_type: str = "assistant"):
        """Envoie un message immediatement au client (sans attendre la fin du traitement)."""
        msg = {"type": msg_type, "content": content, "state": self.state}
        if self.on_send:
            try:
                await self.on_send(msg)
                # Aussi ajouter a l'historique
                self.conversation_history.append({"role": "assistant", "content": content})
                if self.store:
                    self.store.add_message("assistant", content)
            except Exception:
                pass

    async def _step_ingestion(self, files: list[Path], folder: Path) -> list[dict]:
        """Pipeline : Document -> Extraction structurée -> ExtractionStore (RAG) -> FiscalProfile."""
        total = len(files)
        ingested = 0
        skipped = 0
        errors = []

        # Documents déjà traités (reprise de session)
        already_done = {e.get("doc_id") for e in self.extractions.get_all()} if self.extractions else set()

        for i, f in enumerate(files):
            filename = f.name
            pct = int((i / total) * 100)
            print(f"[INGEST] [{i+1}/{total}] {filename}")

            if filename in already_done:
                print(f"[INGEST]   -> Deja extrait, skip")
                skipped += 1
                await self._send_progress({
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "percent": pct,
                    "filename": filename,
                    "status": "skip",
                    "detail": "Deja traite",
                })
                continue

            # Notifier le début du traitement de ce document
            await self._send_progress({
                "type": "progress",
                "current": i + 1,
                "total": total,
                "percent": pct,
                "filename": filename,
                "status": "processing",
                "detail": "Extraction en cours...",
            })

            # 1. Parser le document brut
            doc_data = self.parser.parse(str(f))
            if not doc_data or not doc_data.get("content"):
                errors.append(f"{filename} : contenu non extractible")
                await self._send_progress({
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "percent": pct,
                    "filename": filename,
                    "status": "error",
                    "detail": "Contenu non extractible",
                })
                continue

            # 2. Extraction structurée universelle (1 appel LLM ciblé)
            extraction = await extract_structured(filename, doc_data["content"])

            if extraction and extraction.get("montants"):
                self.extractions.add(extraction)
                ingested += 1
                doc_type = extraction.get("type_document", "?")
                montants_keys = ", ".join(extraction.get("montants", {}).keys())
                await self._send_progress({
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "percent": int(((i + 1) / total) * 100),
                    "filename": filename,
                    "status": "ok",
                    "detail": f"{doc_type} | {montants_keys}",
                })
            elif extraction:
                self.extractions.add(extraction)
                ingested += 1
                await self._send_progress({
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "percent": int(((i + 1) / total) * 100),
                    "filename": filename,
                    "status": "ok",
                    "detail": f"{extraction.get('type_document', '?')} (pas de montants)",
                })
            else:
                errors.append(f"{filename} : extraction echouee")
                await self._send_progress({
                    "type": "progress",
                    "current": i + 1,
                    "total": total,
                    "percent": int(((i + 1) / total) * 100),
                    "filename": filename,
                    "status": "error",
                    "detail": "Extraction echouee",
                })

        # 4. Generer les embeddings en une seule passe (au lieu de a chaque doc)
        if self.extractions:
            await self._send_progress({
                "type": "progress",
                "current": total,
                "total": total,
                "percent": 100,
                "filename": "",
                "status": "processing",
                "detail": "Indexation des extractions...",
            })
            self.extractions.finalize_embeddings()

        # 5. Construire le profil fiscal depuis TOUTES les extractions
        if self.extractions and self.profile:
            profile_data = self.extractions.build_profile_data()
            self.profile.merge_extraction(profile_data, "extraction_store")
            self.profile.save()

        # Résumé pour l'utilisateur
        summary = self.extractions.get_summary() if self.extractions else {}
        completeness = self.profile.get_completeness() if self.profile else 0
        profile_preview = self.profile.get_for_llm() if self.profile else "{}"

        msg = f"**Ingestion terminée** : {ingested} extrait(s), {skipped} déjà traité(s), {len(errors)} erreur(s) sur {total} document(s).\n\n"

        if summary.get("types"):
            msg += "**Types de documents détectés :**\n"
            for doc_type, count in summary["types"].items():
                msg += f"- {doc_type} : {count}\n"
            msg += "\n"

        if summary.get("montants_cles"):
            msg += "**Montants clés extraits :**\n"
            for key, val in summary["montants_cles"].items():
                msg += f"- {key} : {val:,.2f}€\n"
            msg += "\n"

        if summary.get("entites"):
            msg += f"**Entités :** {', '.join(summary['entites'])}\n\n"

        if summary.get("donnees_manquantes"):
            msg += "**Données manquantes signalées :**\n"
            for m in summary["donnees_manquantes"][:5]:
                msg += f"- {m}\n"
            msg += "\n"

        if errors:
            msg += "**Documents non exploitables :**\n"
            for e in errors[:5]:
                msg += f"- {e}\n"
            msg += "\n"

        msg += f"**Profil fiscal** (complétude : {completeness:.0%}) :\n\n"
        msg += f"```json\n{profile_preview[:2000]}\n```\n\n"

        # Passer à la validation
        self.state = STATE_VALIDATION
        self._persist()

        validation_responses = await self._step_validation_detect_missing()
        return [self._msg(msg)] + validation_responses

    # ==================================================================
    # Étape 2 : VALIDATION — détecter les manques et poser des questions
    # ==================================================================

    async def _step_validation_detect_missing(self) -> list[dict]:
        """Analyse le profil et identifie ce qui manque pour le calcul."""
        profile_json = self.profile.get_for_llm()

        rag_context = self.rag.retrieve("parts fiscales situation familiale enfants charges déductibles", top_k=5, max_tokens=2000)

        prompt = (
            f"## Référentiel fiscal\n{rag_context}\n\n"
            f"## Profil fiscal actuel du contribuable\n```json\n{profile_json}\n```\n\n"
            "## Mission\n\n"
            "Analyse ce profil fiscal et identifie TOUTES les informations manquantes "
            "pour pouvoir calculer l'impôt. Génère des questions PRÉCISES pour les obtenir.\n\n"
            "Règles :\n"
            "- Ne demande PAS ce qui est déjà dans le profil\n"
            "- Priorise : situation familiale, nb enfants, régime foncier (si foncier détecté), crédits d'impôt\n"
            "- Maximum 10 questions, classées par importance\n\n"
            "Réponds en JSON :\n"
            "```json\n"
            '{"missing": ["situation familiale", "nombre d\'enfants"], '
            '"questions": ["Quelle est votre situation familiale au 31/12/2025 ?", "..."]}\n'
            "```"
        )

        response = await query_llm(prompt, SYSTEM_PROMPT, temperature=0.2, max_tokens=2000)
        result = _parse_json(response)

        if result and result.get("questions"):
            self.pending_questions = result["questions"]
            self.profile.set_missing_fields(result.get("missing", []))
        else:
            # Construire des questions par défaut basées sur les trous du profil
            self.pending_questions = self._default_questions_from_profile()

        self.current_question_index = 0
        self._persist()

        if not self.pending_questions:
            # Profil complet -> passer au calcul
            self.state = STATE_CALCUL
            self._persist()
            return [
                self._msg("Votre profil fiscal semble complet. Lancement du calcul..."),
                {"type": "status", "content": "Calcul fiscal en cours...", "state": STATE_CALCUL},
                *(await self._step_calcul()),
            ]

        total = len(self.pending_questions)
        return [self._msg(
            f"Il me manque encore **{total} information(s)** pour calculer votre impôt.\n\n"
            f"**Question 1/{total}** :\n{self.pending_questions[0]}"
        )]

    async def _step_validation_answer(self, answer: str) -> list[dict]:
        """Traite une réponse et met à jour le profil."""
        if self.current_question_index < len(self.pending_questions):
            question = self.pending_questions[self.current_question_index]

            # Utiliser le LLM pour structurer la réponse en données de profil
            extraction = await self._structure_answer(question, answer)
            if extraction:
                self.profile.merge_user_answers(extraction)

            self.current_question_index += 1
            self._persist()

        # Question suivante ou passage au calcul
        if self.current_question_index < len(self.pending_questions):
            total = len(self.pending_questions)
            idx = self.current_question_index
            return [self._msg(f"**Question {idx + 1}/{total}** :\n{self.pending_questions[idx]}")]

        # Toutes les questions répondues -> calcul
        self.state = STATE_CALCUL
        self._persist()

        return [
            self._msg("Merci ! Votre profil fiscal est maintenant complet.\n\nLancement du calcul..."),
            {"type": "status", "content": "Calcul fiscal en cours...", "state": STATE_CALCUL},
            *(await self._step_calcul()),
        ]

    async def _structure_answer(self, question: str, answer: str) -> dict | None:
        """Transforme une réponse libre en données structurées pour le profil."""
        prompt = (
            f"Question posée : {question}\n"
            f"Réponse de l'utilisateur : {answer}\n\n"
            "Transforme cette réponse en données structurées pour un profil fiscal JSON.\n"
            "Exemples de clés possibles : foyer.situation, foyer.nb_parts, foyer.nb_enfants_mineurs, "
            "foyer.parent_isole, revenus.foncier_nu, revenus.foncier_meuble, charges_deductibles, "
            "reductions_credits, etc.\n\n"
            "Réponds UNIQUEMENT en JSON partiel (seulement les champs à mettre à jour) :\n"
            '```json\n{"foyer": {"situation": "marié", "nb_enfants_mineurs": 2}}\n```'
        )
        response = await query_llm(prompt, SYSTEM_PROMPT, temperature=0.1, max_tokens=500)
        return _parse_json(response)

    # ==================================================================
    # Étape 3 : CALCUL — RAG + profil JSON -> cases 2042
    # ==================================================================

    async def _step_calcul(self) -> list[dict]:
        """Calcul fiscal basé UNIQUEMENT sur le profil JSON + RAG."""
        profile_json = self.profile.get_for_llm()
        print(f"[CALCUL] Profil JSON : {len(profile_json)} chars")

        # RAG ciblé : chercher les règles pertinentes au profil
        rag_context = self.rag.retrieve(profile_json[:3000], top_k=15, max_tokens=6000)
        print(f"[CALCUL] RAG : {len(rag_context)} chars de règles fiscales")

        prompt = (
            "# RÉFÉRENTIEL FISCAL\n"
            "Utilise UNIQUEMENT ces cases et règles. Ne jamais inventer de numéro de case.\n\n"
            f"{rag_context}\n\n"
            "---\n\n"
            "# PROFIL FISCAL DU CONTRIBUABLE\n"
            "C'est ta SEULE source de données. Tous les montants viennent de ce profil.\n\n"
            f"```json\n{profile_json}\n```\n\n"
            "---\n\n"
            "# INSTRUCTIONS\n\n"
            "1. Pour chaque revenu/charge du profil, identifie la case 2042 correspondante\n"
            "2. Calcule le nombre de parts fiscales\n"
            "3. Applique le barème progressif avec quotient familial\n"
            "4. Applique abattement 10%, décote, réductions et crédits\n"
            "5. Déduis le prélèvement à la source déjà payé\n\n"
            "Réponds UNIQUEMENT en JSON :\n"
            "```json\n"
            "{\n"
            '  "situation": {"situation_familiale": "...", "parts": 0.0, "detail_parts": "..."},\n'
            '  "cases": [\n'
            '    {"case": "1AJ", "libelle": "...", "montant": 0, "justification": "...", "source": "profil.revenus.salaires"}\n'
            "  ],\n"
            '  "calcul_impot": {\n'
            '    "revenu_brut_global": 0, "abattement_10_pct": 0, "revenu_net_imposable": 0,\n'
            '    "nombre_parts": 0, "quotient_familial": 0, "impot_brut": 0,\n'
            '    "decote": 0, "reductions": [], "credits": [],\n'
            '    "impot_net": 0, "prelev_source_deja_paye": 0, "solde": 0,\n'
            '    "detail_bareme": "..."\n'
            "  },\n"
            '  "remarques": []\n'
            "}\n```"
        )

        response = await query_llm(prompt, SYSTEM_PROMPT, temperature=0.15, max_tokens=6000)
        result = _parse_json(response)

        if result:
            print(f"[CALCUL] OK : {len(result.get('cases', []))} cases")
        else:
            print(f"[CALCUL] WARN: JSON invalide, fallback moteur local")
            result = self.engine.compute_from_profile(self.profile.get_raw())

        # Passer à la vérification
        self.state = STATE_VERIFICATION
        self._persist()

        return await self._step_verification(result)

    # ==================================================================
    # Étape 4 : VÉRIFICATION — cross-check cohérence
    # ==================================================================

    async def _step_verification(self, result: dict = None) -> list[dict]:
        """Vérifie la cohérence du calcul et génère le rapport."""
        if result is None:
            result = self.store.get("computation_result") if self.store else None
        if result is None:
            return [self._msg("Erreur : aucun résultat de calcul trouvé.")]

        profile = self.profile.get_raw()
        warnings = []

        # Vérifications automatiques
        calcul = result.get("calcul_impot", {})
        rni = calcul.get("revenu_net_imposable", 0)
        rbg = calcul.get("revenu_brut_global", 0)

        if isinstance(rni, (int, float)) and isinstance(rbg, (int, float)) and rni > rbg > 0:
            warnings.append("Incohérence : revenu net imposable > revenu brut global.")

        if isinstance(calcul.get("impot_net", 0), (int, float)) and calcul.get("impot_net", 0) < 0:
            warnings.append("Impôt net négatif — vérifiez les réductions/crédits.")

        # Vérifier que les cases existent dans le référentiel
        known_cases = set(self.rag.get_all_cases())
        for c in result.get("cases", []):
            case_num = c.get("case", "")
            if case_num and known_cases and case_num not in known_cases:
                warnings.append(f"Case {case_num} non trouvée dans le référentiel.")

        # Cross-check dividendes SASU vs IS
        for soc in profile.get("revenus", {}).get("societe", []):
            if soc.get("type") in ("SASU", "SAS") and soc.get("dividendes", 0) > 0:
                if soc.get("regime_fiscal") == "IS":
                    warnings.append(
                        f"Dividendes {soc['type']} ({soc.get('nom', '?')}) : vérifiez que l'IS a bien été payé "
                        "par la société avant distribution."
                    )

        # Cross-check LMNP seuil LMP
        total_meuble = sum(m.get("recettes_brutes", 0) for m in profile.get("revenus", {}).get("foncier_meuble", []))
        if total_meuble > 23000:
            total_salaires = sum(s.get("net_imposable", 0) for s in profile.get("revenus", {}).get("salaires", []))
            if total_meuble > total_salaires:
                warnings.append(
                    f"Recettes meublées ({total_meuble}€) > salaires ({total_salaires}€) et > 23 000€ : "
                    "vous êtes probablement LMP (Loueur Meublé Professionnel), pas LMNP."
                )

        # Ajouter les warnings au résultat
        if warnings:
            result.setdefault("remarques", [])
            result["remarques"] = warnings + result["remarques"]

        # Sauvegarder le résultat
        if self.store:
            self.store.save_result(result)

        # Générer le rapport
        report_path = self.reporter.generate(result, [], profile)

        if self.store:
            self.store.set("report_path", report_path)

        self.state = STATE_DONE
        self._persist()

        summary = self._build_result_summary(result)

        return [
            self._msg(summary),
            {
                "type": "report",
                "content": "Le rapport détaillé a été sauvegardé.",
                "report_path": report_path,
                "state": STATE_DONE,
            },
        ]

    # ==================================================================
    # Utilitaires
    # ==================================================================

    def _get_resume_message(self) -> str:
        """Message de reprise de session."""
        completeness = self.profile.get_completeness()
        already_extracted = len(self.extractions.get_all()) if self.extractions else 0

        msg = "**Session reprise**\n\n"

        if self.state == STATE_INGESTION:
            msg += f"{already_extracted} document(s) deja analyse(s).\n\n"
            msg += "Tapez **ok** pour reprendre l'analyse des documents restants."

        elif self.state == STATE_VALIDATION:
            msg += f"{already_extracted} document(s) analyses. Completude : {completeness:.0%}\n"
            q_done = self.current_question_index
            q_total = len(self.pending_questions)
            msg += f"{q_done}/{q_total} questions repondues.\n\n"
            if self.current_question_index < len(self.pending_questions):
                msg += f"**Question {q_done + 1}/{q_total}** :\n{self.pending_questions[q_done]}"

        elif self.state == STATE_CALCUL:
            msg += f"{already_extracted} document(s) analyses. Completude : {completeness:.0%}\n\n"
            msg += "Profil complet. Tapez **ok** pour lancer le calcul."

        elif self.state == STATE_DONE:
            msg += "Le rapport a deja ete genere. Consultez `output/`."

        else:
            msg += f"Etat : {self.state}"

        return msg

    def _default_questions_from_profile(self) -> list[str]:
        """Génère des questions par défaut basées sur les trous du profil."""
        questions = []
        p = self.profile.data

        if not p["foyer"]["situation"]:
            questions.append("Quelle est votre situation familiale au 31/12/2025 ? (célibataire, marié(e), pacsé(e), divorcé(e), veuf/veuve)")
        if p["foyer"]["nb_parts"] == 0:
            questions.append("Combien d'enfants avez-vous à charge ? (mineurs, ou majeurs rattachés < 25 ans)")
        if not p["revenus"]["salaires"] and not p["revenus"]["pensions_retraite"]:
            questions.append("Quels sont vos revenus principaux ? (salaires, pensions, etc.)")
        if p["revenus"]["foncier_nu"] and not any(f.get("regime") for f in p["revenus"]["foncier_nu"]):
            questions.append("Pour vos revenus fonciers, êtes-vous au régime micro-foncier ou au régime réel ?")
        if p["revenus"]["foncier_meuble"] and not any(f.get("regime") for f in p["revenus"]["foncier_meuble"]):
            questions.append("Pour vos locations meublées, êtes-vous au régime micro-BIC ou au régime réel ?")

        if not questions:
            questions = [
                "Avez-vous d'autres revenus non détectés dans les documents ? (foncier, dividendes, micro-entreprise, etc.)",
                "Avez-vous des charges déductibles ? (dons, emploi à domicile, PER, pension alimentaire, etc.)",
            ]

        return questions

    def _build_result_summary(self, result: dict) -> str:
        """Résumé du résultat pour le chat."""
        text = "## Résultat de votre déclaration fiscale\n\n"

        situation = result.get("situation", {})
        if situation:
            text += f"**Situation** : {situation.get('situation_familiale', '?')} — "
            text += f"{situation.get('parts', '?')} part(s)"
            if situation.get("detail_parts"):
                text += f" ({situation['detail_parts']})"
            text += "\n\n"

        cases = result.get("cases", [])
        if cases:
            text += "### Cases à remplir\n\n"
            text += "| Case | Libellé | Montant | Justification |\n"
            text += "|------|---------|---------|---------------|\n"
            for c in cases:
                montant = c.get("montant", 0)
                montant_str = f"{montant:,.2f} €".replace(",", " ").replace(".", ",") if isinstance(montant, (int, float)) else str(montant)
                text += f"| **{c.get('case', '?')}** | {c.get('libelle', '')} | {montant_str} | {str(c.get('justification', ''))[:60]} |\n"
            text += "\n"

        calcul = result.get("calcul_impot", {})
        if calcul:
            def fmt(v):
                return f"{v:,.2f} €".replace(",", " ").replace(".", ",") if isinstance(v, (int, float)) else str(v)

            text += "### Calcul\n\n"
            text += f"- Revenu brut global : **{fmt(calcul.get('revenu_brut_global', 0))}**\n"
            text += f"- Revenu net imposable : **{fmt(calcul.get('revenu_net_imposable', 0))}**\n"
            text += f"- Parts : **{calcul.get('nombre_parts', '?')}**\n"
            text += f"- Impôt brut : **{fmt(calcul.get('impot_brut', 0))}**\n"
            text += f"- Impôt net : **{fmt(calcul.get('impot_net', 0))}**\n"
            text += f"- PAS déjà payé : **- {fmt(calcul.get('prelev_source_deja_paye', 0))}**\n"

            solde = calcul.get("solde", 0)
            if isinstance(solde, (int, float)):
                if solde > 0:
                    text += f"\n**Solde à payer : {fmt(solde)}**\n"
                elif solde < 0:
                    text += f"\n**Remboursement estimé : {fmt(abs(solde))}**\n"

            if calcul.get("detail_bareme"):
                text += f"\n*Barème :* {calcul['detail_bareme']}\n"

        remarques = result.get("remarques", [])
        if remarques:
            text += "\n### Remarques\n"
            for r in remarques:
                text += f"- {r}\n"

        text += "\n---\n*Vérifiez chaque montant avant de soumettre sur impots.gouv.fr.*"
        return text

    def _msg(self, content: str) -> dict:
        return {"type": "assistant", "content": content, "state": self.state}


def _parse_json(text: str) -> dict | None:
    """Parse JSON depuis une réponse LLM."""
    if not text or text.startswith("ERREUR"):
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    depth = 0
    start = -1
    best = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0: start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    c = json.loads(text[start:i+1])
                    if best is None or len(text[start:i+1]) > len(json.dumps(best)):
                        best = c
                except json.JSONDecodeError:
                    pass
                start = -1
    return best
