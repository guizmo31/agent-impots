"""
Agent Fiscal - Logique conversationnelle pour la déclaration d'impôts.
Gère le flux de dialogue étape par étape.
"""
import json
import re
from pathlib import Path

from ollama_client import query_llm, check_ollama_status
from document_parser import DocumentParser
from fiscal_engine import FiscalEngine
from report_generator import ReportGenerator
from rag import FiscalRAG
from session_store import SessionStore

SYSTEM_PROMPT = """Tu es un assistant fiscal expert en déclaration d'impôts sur le revenu en France.
Tu aides les contribuables à remplir leur déclaration (formulaire 2042 et annexes).

## Tes compétences
- Analyse de bulletins de paie, avis d'imposition, relevés bancaires, factures
- Identification des cases du formulaire 2042 (1AJ, 4BA, 7DB, etc.)
- Calcul de l'impôt : barème progressif, quotient familial, décote, réductions/crédits
- Connaissance des régimes : salaires, foncier (nu/meublé), capitaux mobiliers, micro-entreprise, RSU/stock-options

## Règles strictes
1. UTILISE UNIQUEMENT le référentiel fiscal fourni dans le prompt. Ne jamais inventer un numéro de case.
2. Quand tu cites un montant, indique TOUJOURS : la case, le calcul, et le document source.
3. Si une information est ambiguë ou manquante, dis-le explicitement — ne devine pas.
4. Quand on te demande du JSON, réponds UNIQUEMENT avec du JSON valide, sans texte avant ni après.
5. Tu ne donnes JAMAIS de conseils d'optimisation fiscale illégale.
6. Tu es un outil d'aide — tu rappelles que la déclaration doit être vérifiée par le contribuable.
"""

# Etapes du dialogue
STATE_WELCOME = "welcome"
STATE_SCAN_FOLDER = "scan_folder"
STATE_ANALYZE_DOCS = "analyze_docs"
STATE_QUESTIONS = "questions"
STATE_COMPUTE = "compute"
STATE_REPORT = "report"
STATE_DONE = "done"


class AgentFiscal:
    def __init__(self, document_parser: DocumentParser, fiscal_engine: FiscalEngine, report_generator: ReportGenerator, session_id: str = ""):
        self.parser = document_parser
        self.engine = fiscal_engine
        self.reporter = report_generator
        self.rag = FiscalRAG()

        # Mémoire persistante
        self.store = SessionStore(session_id) if session_id else None
        self._restore_from_store()

    def _restore_from_store(self):
        """Restaure l'état de l'agent depuis la mémoire persistante."""
        if self.store and not self.store.is_new():
            print(f"[SESSION] Restauration de la session : {self.store.session_id}")
            self.state = self.store.get("state", STATE_WELCOME)
            self.documents_path = self.store.get("documents_path", "")
            self.parsed_documents = self.store.get_documents()
            self.user_profile = self.store.get_profile()
            self.conversation_history = self.store.get_history()
            self.pending_questions = self.store.get("pending_questions", [])
            self.current_question_index = self.store.get("current_question_index", 0)
        else:
            self.state = STATE_WELCOME
            self.documents_path = ""
            self.parsed_documents = []
            self.user_profile = {}
            self.conversation_history = []
            self.pending_questions = []
            self.current_question_index = 0
            # Initialiser la session si store existe
            if self.store:
                self.store.init_session()

    def _persist(self):
        """Sauvegarde l'état courant dans la mémoire persistante."""
        if not self.store:
            return
        self.store.set_many({
            "state": self.state,
            "documents_path": self.documents_path,
            "pending_questions": self.pending_questions,
            "current_question_index": self.current_question_index,
        })
        self.store.save_profile(self.user_profile)
        # L'historique est sauvegardé via add_message
        # Les documents sont sauvegardés dans _handle_analysis

    def get_welcome_message(self) -> str:
        # Si session restaurée, reprendre là où on en était
        if self.store and not self.store.is_new() and self.state != STATE_WELCOME:
            return self._get_resume_message()

        return (
            "Bonjour ! Je suis votre assistant fiscal local. Je vais vous aider à "
            "préparer votre déclaration d'impôts.\n\n"
            "**Toutes vos données restent sur votre ordinateur** — rien n'est envoyé sur internet.\n\n"
            "Pour commencer, veuillez m'indiquer le **chemin du dossier** sur votre PC "
            "où se trouvent vos documents fiscaux (bulletins de paie, relevés bancaires, "
            "attestations, factures, etc.).\n\n"
            "Exemple : `C:\\Users\\MonNom\\Documents\\Impots2025`"
        )

    def _get_resume_message(self) -> str:
        """Message de reprise de session."""
        summary = self.store.get_summary()
        docs_count = summary["documents_count"]
        q_answered = summary["questions_answered"]
        q_total = summary["questions_total"]
        notes = self.store.get_notes()

        msg = (
            f"Bon retour ! Je reprends votre session **{summary['name']}** "
            f"(commencée le {summary['created_at'][:10]}).\n\n"
        )

        if docs_count > 0:
            msg += f"**{docs_count} document(s)** déjà analysé(s).\n"

        if self.state == STATE_QUESTIONS and q_total > 0:
            msg += f"**{q_answered}/{q_total} questions** déjà répondues.\n\n"
            if self.current_question_index < len(self.pending_questions):
                next_q = self.pending_questions[self.current_question_index]
                msg += f"On reprend là où on s'était arrêté :\n\n"
                msg += f"**Question {self.current_question_index + 1}/{q_total}** :\n{next_q}"
            else:
                msg += "Toutes les questions ont été répondues. Tapez **ok** pour lancer le calcul."
                self.state = STATE_COMPUTE

        elif self.state == STATE_SCAN_FOLDER:
            msg += "Veuillez m'indiquer le chemin du dossier contenant vos documents fiscaux."

        elif self.state == STATE_DONE:
            report_path = summary.get("report_path")
            msg += "Le rapport a déjà été généré."
            if report_path:
                msg += f"\nVous pouvez le consulter dans le dossier `output/`."
            msg += "\nRechargez la page pour commencer une nouvelle déclaration."

        elif self.state == STATE_COMPUTE:
            msg += "Les informations sont complètes. Tapez **ok** pour lancer le calcul fiscal."

        # Afficher les notes mémorisées
        if notes:
            msg += "\n\n**Notes mémorisées :**\n"
            for note in notes[-5:]:  # Dernières 5 notes
                msg += f"- {note['content']}\n"

        return msg

    async def process_message(self, user_message: str) -> list[dict]:
        """Traite un message utilisateur et retourne une liste de réponses."""
        self.conversation_history.append({"role": "user", "content": user_message})
        if self.store:
            self.store.add_message("user", user_message)

        responses = []

        if self.state == STATE_WELCOME:
            responses = await self._handle_folder_input(user_message)
        elif self.state == STATE_SCAN_FOLDER:
            responses = await self._handle_folder_input(user_message)
        elif self.state == STATE_ANALYZE_DOCS:
            responses = await self._handle_analysis()
        elif self.state == STATE_QUESTIONS:
            responses = await self._handle_question_answer(user_message)
        elif self.state == STATE_COMPUTE:
            responses = await self._handle_computation()
        elif self.state == STATE_REPORT:
            responses = await self._handle_report_generation()
        elif self.state == STATE_DONE:
            responses = [self._msg(
                "Le rapport a déjà été généré. Vous pouvez le consulter dans le dossier `output/`. "
                "Si vous souhaitez recommencer avec de nouveaux documents, rechargez la page."
            )]

        for r in responses:
            if r.get("type") == "assistant":
                self.conversation_history.append({"role": "assistant", "content": r["content"]})
                if self.store:
                    self.store.add_message("assistant", r["content"])

        # Auto-save après chaque échange
        self._persist()

        return responses

    # ------------------------------------------------------------------
    # Étape 1 : Saisie du dossier
    # ------------------------------------------------------------------

    async def _handle_folder_input(self, folder_path: str) -> list[dict]:
        """Gère la saisie du chemin du dossier de documents."""
        folder_path = folder_path.strip().strip('"').strip("'")

        folder = Path(folder_path)
        if not folder.exists():
            return [self._msg(
                f"Le dossier `{folder_path}` n'existe pas. "
                "Veuillez vérifier le chemin et réessayer."
            )]

        if not folder.is_dir():
            return [self._msg(
                f"`{folder_path}` n'est pas un dossier. "
                "Veuillez indiquer le chemin d'un dossier contenant vos documents."
            )]

        self.documents_path = str(folder)
        self.state = STATE_ANALYZE_DOCS

        supported_ext = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".xlsx", ".xls", ".csv", ".docx", ".txt"}
        files_found = []
        for f in folder.rglob("*"):
            if f.is_file() and f.suffix.lower() in supported_ext:
                files_found.append(str(f.relative_to(folder)))

        if not files_found:
            self.state = STATE_SCAN_FOLDER
            return [self._msg(
                f"Aucun document exploitable trouvé dans `{folder_path}`.\n\n"
                "Formats supportés : PDF, PNG, JPG, XLSX, CSV, DOCX, TXT.\n\n"
                "Veuillez indiquer un autre dossier."
            )]

        file_list = "\n".join(f"  - `{f}`" for f in files_found)
        return [
            self._msg(
                f"J'ai trouvé **{len(files_found)} document(s)** dans `{folder_path}` :\n\n"
                f"{file_list}\n\n"
                "Je vais maintenant analyser ces documents pour en extraire les informations fiscales. "
                "Cela peut prendre quelques instants..."
            ),
            {"type": "status", "content": "Analyse des documents en cours...", "state": self.state},
            *(await self._handle_analysis()),
        ]

    # ------------------------------------------------------------------
    # Étape 2 : Analyse des documents
    # ------------------------------------------------------------------

    async def _handle_analysis(self) -> list[dict]:
        """Analyse tous les documents trouvés."""
        folder = Path(self.documents_path)
        supported_ext = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".xlsx", ".xls", ".csv", ".docx", ".txt"}

        self.parsed_documents = []
        for f in folder.rglob("*"):
            if f.is_file() and f.suffix.lower() in supported_ext:
                doc_data = self.parser.parse(str(f))
                if doc_data and doc_data.get("content"):
                    self.parsed_documents.append(doc_data)
                    print(f"[DOC] Parsé : {doc_data['filename']} ({len(doc_data['content'])} chars)")

        if not self.parsed_documents:
            self.state = STATE_SCAN_FOLDER
            return [self._msg(
                "Je n'ai pas pu extraire de contenu exploitable des documents. "
                "Vérifiez que les PDF ne sont pas protégés et que les images sont lisibles.\n\n"
                "Veuillez indiquer un autre dossier ou ajouter des documents."
            )]

        # Persister les documents parsés
        if self.store:
            self.store.save_documents(self.parsed_documents)
            self.store.set("documents_path", self.documents_path)

        total_chars = sum(len(d.get("content", "")) for d in self.parsed_documents)
        print(f"[DOC] Total : {len(self.parsed_documents)} documents, {total_chars} chars")

        # --- Stratégie adaptative selon le volume ---
        # Si beaucoup de documents, analyser par lots puis fusionner
        MAX_CHARS_PER_CALL = 25000  # ~6000 tokens, laisse de la place pour le prompt et la réponse

        if total_chars > MAX_CHARS_PER_CALL:
            print(f"[AGENT] Volume important ({total_chars} chars) — analyse par lots")
            all_analysis = await self._analyze_documents_in_batches(MAX_CHARS_PER_CALL)
        else:
            all_analysis = await self._analyze_documents_single_call()

        if all_analysis and "questions" in all_analysis:
            self.pending_questions = all_analysis["questions"]
            self.user_profile["documents_analysis"] = all_analysis.get("documents_analysis", [])
            print(f"[AGENT] {len(all_analysis.get('documents_analysis', []))} documents identifiés, {len(self.pending_questions)} questions générées")
        else:
            print(f"[AGENT] WARN: Analyse LLM échouée, utilisation des questions par défaut")
            self.pending_questions = self._get_default_questions()
            self.user_profile["documents_analysis"] = []

        self.current_question_index = 0
        self.state = STATE_QUESTIONS

        # Message pour l'utilisateur
        analysis_text = f"**Analyse des {len(self.parsed_documents)} documents terminée.**\n\n"
        if self.user_profile.get("documents_analysis"):
            analysis_text += "**Documents identifiés :**\n"
            for doc in self.user_profile["documents_analysis"]:
                analysis_text += f"- **{doc.get('filename', '?')}** : {doc.get('type', '?')} — {doc.get('key_info', '')}\n"
            analysis_text += "\n"
        else:
            analysis_text += (
                "Je n'ai pas pu classifier automatiquement tous les documents, "
                "mais je vais quand même vous poser les questions essentielles.\n\n"
            )

        analysis_text += (
            "J'ai maintenant besoin de vous poser quelques questions pour compléter votre profil fiscal.\n\n"
            f"**Question 1/{len(self.pending_questions)}** :\n"
            f"{self.pending_questions[0]}"
        )

        return [self._msg(analysis_text)]

    async def _analyze_documents_single_call(self) -> dict | None:
        """Analyse tous les documents en un seul appel LLM (petit volume)."""
        docs_summary = self._build_docs_summary()
        rag_context = self.rag.retrieve(docs_summary[:5000], top_k=6, max_tokens=2000)
        prompt = self._build_classification_prompt(docs_summary, rag_context)

        llm_response = await query_llm(prompt, SYSTEM_PROMPT, temperature=0.2, max_tokens=4096)
        return self._parse_llm_json(llm_response)

    async def _analyze_documents_in_batches(self, max_chars_per_batch: int) -> dict | None:
        """Analyse les documents par lots, puis fusionne les résultats."""
        # 1. Répartir les documents en lots
        batches: list[list[dict]] = []
        current_batch: list[dict] = []
        current_size = 0

        for doc in self.parsed_documents:
            doc_size = len(doc.get("content", ""))
            # Chaque document individuel est limité à 2000 chars pour les lots
            if current_size + min(doc_size, 2000) > max_chars_per_batch and current_batch:
                batches.append(current_batch)
                current_batch = []
                current_size = 0
            current_batch.append(doc)
            current_size += min(doc_size, 2000)

        if current_batch:
            batches.append(current_batch)

        print(f"[AGENT] Analyse en {len(batches)} lot(s)")

        # 2. Analyser chaque lot
        all_docs_analysis = []
        all_detected_topics = set()

        for i, batch in enumerate(batches):
            print(f"[AGENT] Lot {i+1}/{len(batches)} ({len(batch)} documents)...")

            # Construire le résumé du lot (version compacte)
            batch_summary_parts = []
            for doc in batch:
                content = doc.get("content", "")
                filename = doc.get("filename", "?")
                # En mode lot, on garde seulement 2000 chars par document
                if len(content) > 2000:
                    content = content[:1200] + "\n[...]\n" + content[-600:]
                batch_summary_parts.append(f"### {filename}\n{content}")

            batch_summary = "\n\n---\n\n".join(batch_summary_parts)

            batch_prompt = (
                f"## Documents (lot {i+1}/{len(batches)})\n\n{batch_summary}\n\n"
                "## Mission\n\n"
                "Pour chaque document, identifie :\n"
                "1. Le type (bulletin de paie, avis d'imposition, relevé, facture, prêt, taxe foncière, etc.)\n"
                "2. Les montants et informations fiscales clés\n"
                "3. L'année concernée\n\n"
                "Réponds UNIQUEMENT en JSON valide :\n"
                "```json\n"
                '{"documents_analysis": [\n'
                '  {"filename": "...", "type": "...", "key_info": "...", "year": "..."}\n'
                "]}\n```"
            )

            response = await query_llm(batch_prompt, SYSTEM_PROMPT, temperature=0.2, max_tokens=3000)
            batch_result = self._parse_llm_json(response)

            if batch_result and "documents_analysis" in batch_result:
                for doc_info in batch_result["documents_analysis"]:
                    all_docs_analysis.append(doc_info)
                    # Collecter les types de documents pour adapter les questions
                    doc_type = doc_info.get("type", "").lower()
                    all_detected_topics.add(doc_type)

        # 3. Générer les questions basées sur l'ensemble des documents détectés
        print(f"[AGENT] Documents identifiés : {len(all_docs_analysis)}, topics : {all_detected_topics}")

        topics_summary = ", ".join(all_detected_topics) if all_detected_topics else "inconnus"
        docs_info_summary = "\n".join(
            f"- {d.get('filename', '?')} : {d.get('type', '?')} — {d.get('key_info', '')}"
            for d in all_docs_analysis
        )

        rag_context = self.rag.retrieve(
            f"déclaration impôts {topics_summary} revenus fonciers salaires",
            top_k=6, max_tokens=2000,
        )

        questions_prompt = (
            f"## Référentiel fiscal\n{rag_context}\n\n"
            f"## Documents identifiés chez le contribuable\n\n{docs_info_summary}\n\n"
            f"Types de documents trouvés : {topics_summary}\n\n"
            "## Mission\n\n"
            "Sur la base des documents identifiés ci-dessus, génère les questions ESSENTIELLES "
            "à poser au contribuable pour compléter sa déclaration. "
            "Adapte les questions aux types de documents trouvés. "
            "Ne pose PAS de question dont la réponse est déjà dans les documents.\n\n"
            "Réponds UNIQUEMENT en JSON valide :\n"
            '```json\n{"questions": ["question 1", "question 2", ...]}\n```'
        )

        q_response = await query_llm(questions_prompt, SYSTEM_PROMPT, temperature=0.2, max_tokens=2000)
        q_result = self._parse_llm_json(q_response)

        questions = q_result.get("questions", []) if q_result else []
        if not questions:
            questions = self._get_default_questions()

        return {
            "documents_analysis": all_docs_analysis,
            "questions": questions,
        }

    def _build_classification_prompt(self, docs_summary: str, rag_context: str) -> str:
        """Construit le prompt de classification (appel unique)."""
        return (
            f"## Référentiel fiscal\n{rag_context}\n\n"
            f"## Documents fournis par le contribuable\n\n{docs_summary}\n\n"
            "## Ta mission\n\n"
            "Analyse ATTENTIVEMENT chaque document ci-dessus. Pour chacun :\n"
            "1. Identifie le type (bulletin de paie, avis d'imposition, relevé, facture, etc.)\n"
            "2. Extrais TOUS les montants fiscaux importants (net imposable, cumul, prélèvement à la source, etc.)\n"
            "3. Identifie l'année fiscale\n\n"
            "Ensuite, génère des questions PERTINENTES basées sur ce que tu as vu dans les documents. "
            "Ne pose PAS de question dont la réponse est déjà dans les documents.\n\n"
            "Réponds UNIQUEMENT en JSON valide :\n"
            "```json\n"
            "{\n"
            '  "documents_analysis": [\n'
            '    {"filename": "nom_fichier.pdf", "type": "bulletin de paie", "key_info": "Net imposable annuel: 32 450€, PAS retenu: 2 890€", "year": "2025"}\n'
            "  ],\n"
            '  "questions": [\n'
            '    "Quelle est votre situation familiale ?",\n'
            '    "Combien d\'enfants avez-vous à charge ?"\n'
            "  ]\n"
            "}\n"
            "```"
        )

    # ------------------------------------------------------------------
    # Étape 3 : Questions / Réponses
    # ------------------------------------------------------------------

    async def _handle_question_answer(self, answer: str) -> list[dict]:
        """Gère les réponses aux questions du profil fiscal."""
        if self.current_question_index < len(self.pending_questions):
            question = self.pending_questions[self.current_question_index]
            self.user_profile[f"q{self.current_question_index}"] = {
                "question": question,
                "answer": answer,
            }
            self.current_question_index += 1

        if self.current_question_index < len(self.pending_questions):
            next_q = self.pending_questions[self.current_question_index]
            total = len(self.pending_questions)
            return [self._msg(
                f"**Question {self.current_question_index + 1}/{total}** :\n{next_q}"
            )]

        # Toutes les questions posées → calcul
        self.state = STATE_COMPUTE
        return [
            self._msg(
                "Merci pour toutes ces informations !\n\n"
                "Je vais maintenant procéder au calcul de votre déclaration fiscale. "
                "Cela peut prendre un moment..."
            ),
            {"type": "status", "content": "Calcul fiscal en cours...", "state": self.state},
            *(await self._handle_computation()),
        ]

    # ------------------------------------------------------------------
    # Étape 4 : Calcul fiscal
    # ------------------------------------------------------------------

    async def _handle_computation(self) -> list[dict]:
        """Calcule les montants fiscaux et génère le rapport."""
        profile_summary = self._build_profile_summary()
        history_summary = self._build_history_summary()

        # Pour le calcul, utiliser le résumé structuré des documents (pas le texte brut)
        # Ça évite d'envoyer 86k chars au LLM
        docs_for_computation = self._build_docs_summary_for_computation()
        print(f"[AGENT] Résumé documents pour calcul : {len(docs_for_computation)} chars")

        # RAG : rechercher les règles pertinentes
        rag_query = f"calcul impôt {profile_summary[:2000]} {docs_for_computation[:2000]}"
        rag_context = self.rag.retrieve(rag_query, top_k=15, max_tokens=6000)
        print(f"[RAG] {len(rag_context)} chars de contexte fiscal injectés")

        computation_prompt = (
            "# RÉFÉRENTIEL FISCAL OFFICIEL\n"
            "Utilise UNIQUEMENT les cases et règles ci-dessous. Ne jamais inventer de numéro de case.\n\n"
            f"{rag_context}\n\n"
            "---\n\n"
            "# DOCUMENTS DU CONTRIBUABLE\n"
            "Voici les informations extraites des documents fiscaux.\n\n"
            f"{docs_for_computation}\n\n"
            "---\n\n"
            "# PROFIL DU CONTRIBUABLE (réponses aux questions)\n\n"
            f"{profile_summary}\n\n"
        )

        if history_summary:
            computation_prompt += (
                "---\n\n"
                "# HISTORIQUE DE LA CONVERSATION\n\n"
                f"{history_summary}\n\n"
            )

        computation_prompt += (
            "---\n\n"
            "# INSTRUCTIONS DE CALCUL\n\n"
            "Sur la base de TOUTES les informations ci-dessus :\n\n"
            "1. **Identifie chaque revenu** dans les documents et la case 2042 correspondante\n"
            "2. **Calcule le nombre de parts** fiscales selon la situation familiale\n"
            "3. **Calcule l'impôt** avec le barème progressif et le quotient familial\n"
            "4. **Applique** l'abattement de 10%, la décote, les réductions et crédits d'impôt\n"
            "5. **Déduis** le prélèvement à la source déjà payé\n\n"
            "Réponds UNIQUEMENT en JSON valide :\n"
            "```json\n"
            "{\n"
            '  "situation": {\n'
            '    "situation_familiale": "marié",\n'
            '    "parts": 3.0,\n'
            '    "detail_parts": "2 parts (couple) + 0.5 (1er enfant) + 0.5 (2ème enfant)"\n'
            "  },\n"
            '  "cases": [\n'
            '    {\n'
            '      "case": "1AJ",\n'
            '      "libelle": "Salaires déclarant 1",\n'
            '      "montant": 32450.00,\n'
            '      "justification": "Cumul net imposable annuel figurant sur le bulletin de paie de décembre 2025",\n'
            '      "source": "bulletin_dec_2025.pdf"\n'
            "    }\n"
            "  ],\n"
            '  "calcul_impot": {\n'
            '    "revenu_brut_global": 32450.00,\n'
            '    "abattement_10_pct": 3245.00,\n'
            '    "revenu_net_imposable": 29205.00,\n'
            '    "nombre_parts": 3.0,\n'
            '    "quotient_familial": 9735.00,\n'
            '    "impot_brut": 0.00,\n'
            '    "decote": 0.00,\n'
            '    "reductions": [],\n'
            '    "credits": [],\n'
            '    "impot_net": 0.00,\n'
            '    "prelev_source_deja_paye": 2890.00,\n'
            '    "solde": -2890.00,\n'
            '    "detail_bareme": "QF = 9 735€ < 11 497€ → tranche à 0%, impôt brut = 0€"\n'
            "  },\n"
            '  "remarques": [\n'
            '    "Le prélèvement à la source de 2 890€ a été extrait du bulletin de paie",\n'
            '    "Vérifiez le montant exact sur votre espace impots.gouv.fr"\n'
            "  ]\n"
            "}\n"
            "```\n\n"
            "IMPORTANT : Respecte EXACTEMENT ce format JSON. Les montants sont des nombres (pas de chaînes)."
        )

        llm_response = await query_llm(
            computation_prompt, SYSTEM_PROMPT,
            temperature=0.15, max_tokens=6000,
        )
        result = self._parse_llm_json(llm_response)

        if result:
            print(f"[AGENT] LLM a retourné un calcul avec {len(result.get('cases', []))} cases")
            # Valider la cohérence
            warnings = self._validate_result(result)
            if warnings:
                existing = result.get("remarques", [])
                result["remarques"] = warnings + existing
        else:
            print(f"[AGENT] WARN: JSON LLM invalide, fallback sur le moteur de calcul local")
            print(f"[AGENT] Réponse LLM (500 premiers chars): {llm_response[:500]}")
            result = self.engine.compute_from_documents(self.parsed_documents, self.user_profile)
            result.setdefault("remarques", []).insert(0,
                "Le calcul a été effectué par le moteur local (le modèle LLM n'a pas pu produire un résultat structuré). "
                "Les montants peuvent être incomplets — vérifiez avec vos documents."
            )

        self.state = STATE_REPORT

        report_path = self.reporter.generate(result, self.parsed_documents, self.user_profile)
        summary = self._build_result_summary(result)

        # Persister le résultat et le chemin du rapport
        if self.store:
            self.store.save_result(result)
            self.store.set("report_path", report_path)
            self.store.set("state", STATE_DONE)

        return [
            self._msg(summary),
            {
                "type": "report",
                "content": "Le rapport détaillé a été sauvegardé.",
                "report_path": report_path,
                "state": STATE_DONE,
            },
        ]

    # ------------------------------------------------------------------
    # Construction des résumés
    # ------------------------------------------------------------------

    def _build_docs_summary(self) -> str:
        """Construit un résumé textuel complet de tous les documents parsés."""
        parts = []
        for doc in self.parsed_documents:
            content = doc.get("content", "")
            filename = doc.get("filename", "Document")
            size = doc.get("size_bytes", 0)

            # Limite plus généreuse : 8000 chars par document
            # Pour les très gros documents, garder le début ET la fin (souvent les cumuls annuels)
            if len(content) > 8000:
                head = content[:5000]
                tail = content[-2500:]
                content = (
                    f"{head}\n\n"
                    f"[... {len(content) - 7500} caractères omis ...]\n\n"
                    f"[FIN DU DOCUMENT]\n{tail}"
                )

            parts.append(
                f"### Document : {filename}\n"
                f"Taille : {size} octets | Contenu extrait ({len(content)} chars) :\n\n"
                f"{content}"
            )
        return "\n\n---\n\n".join(parts)

    def _build_docs_summary_for_computation(self) -> str:
        """Construit un résumé COMPACT des documents pour l'étape de calcul.

        Utilise les analyses déjà faites (étape 2) + les montants clés extraits.
        Beaucoup plus court que le texte brut, mais contient toute l'info utile.
        """
        parts = []

        # 1. D'abord les analyses structurées (résumé de l'étape 2)
        docs_analysis = self.user_profile.get("documents_analysis", [])
        if docs_analysis:
            parts.append("## Synthèse des documents analysés\n")
            for doc in docs_analysis:
                parts.append(
                    f"- **{doc.get('filename', '?')}** [{doc.get('type', '?')}] "
                    f"(année {doc.get('year', '?')}) : {doc.get('key_info', 'N/A')}"
                )
            parts.append("")

        # 2. Puis le contenu brut mais tronqué — focus sur les montants
        parts.append("## Contenu détaillé des documents\n")
        budget_per_doc = 2000 if len(self.parsed_documents) > 10 else 4000
        total_budget = 30000  # Max ~7500 tokens de documents
        used = 0

        for doc in self.parsed_documents:
            if used >= total_budget:
                parts.append(f"\n[... {len(self.parsed_documents)} documents au total — contenu tronqué pour le calcul ...]")
                break

            content = doc.get("content", "")
            filename = doc.get("filename", "?")

            # Extraire les lignes contenant des montants (plus utiles pour le calcul)
            important_lines = []
            other_lines = []
            for line in content.split("\n"):
                line_stripped = line.strip()
                if not line_stripped:
                    continue
                # Ligne avec un montant ou un mot-clé fiscal
                if re.search(r"\d[\d\s]*[,\.]\d{2}", line_stripped) or \
                   re.search(r"(?:net|brut|imposable|cumul|total|impôt|prélèvement|taxe|revenu|loyer|salaire)", line_stripped, re.IGNORECASE):
                    important_lines.append(line_stripped)
                else:
                    other_lines.append(line_stripped)

            # Prioriser les lignes importantes
            if important_lines:
                doc_content = "\n".join(important_lines[:50])
                if len(doc_content) > budget_per_doc:
                    doc_content = doc_content[:budget_per_doc]
            else:
                doc_content = content[:budget_per_doc]

            parts.append(f"### {filename}\n{doc_content}")
            used += len(doc_content)

        return "\n\n".join(parts)

    def _build_profile_summary(self) -> str:
        """Construit un résumé du profil fiscal."""
        parts = []
        for key, value in self.user_profile.items():
            if key.startswith("q") and isinstance(value, dict):
                parts.append(f"- **{value['question']}**\n  Réponse : {value['answer']}")
        return "\n".join(parts) if parts else "(Aucune réponse collectée)"

    def _build_history_summary(self) -> str:
        """Construit un résumé de l'historique de conversation (derniers échanges pertinents)."""
        if len(self.conversation_history) <= 4:
            return ""
        # Inclure les 10 derniers messages (hors le tout premier welcome)
        recent = self.conversation_history[-10:]
        parts = []
        for msg in recent:
            role = "Utilisateur" if msg["role"] == "user" else "Agent"
            content = msg["content"][:300]
            parts.append(f"**{role}** : {content}")
        return "\n".join(parts)

    def _build_result_summary(self, result: dict) -> str:
        """Construit un résumé lisible du résultat fiscal."""
        text = "## Résultat de votre déclaration fiscale\n\n"

        situation = result.get("situation", {})
        if situation:
            text += f"**Situation** : {situation.get('situation_familiale', 'N/A')} — "
            text += f"{situation.get('parts', '?')} part(s) fiscale(s)"
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
                if isinstance(montant, (int, float)):
                    montant_str = f"{montant:,.2f} €".replace(",", " ").replace(".", ",")
                else:
                    montant_str = str(montant)
                justif = str(c.get("justification", ""))[:80]
                text += f"| **{c.get('case', '?')}** | {c.get('libelle', '')} | {montant_str} | {justif} |\n"
            text += "\n"

        calcul = result.get("calcul_impot", {})
        if calcul:
            text += "### Calcul de l'impôt\n\n"

            def fmt(v):
                if isinstance(v, (int, float)):
                    return f"{v:,.2f} €".replace(",", " ").replace(".", ",")
                return str(v)

            text += f"- Revenu brut global : **{fmt(calcul.get('revenu_brut_global', 0))}**\n"
            if calcul.get("abattement_10_pct"):
                text += f"- Abattement 10% : **- {fmt(calcul.get('abattement_10_pct', 0))}**\n"
            text += f"- Revenu net imposable : **{fmt(calcul.get('revenu_net_imposable', 0))}**\n"
            text += f"- Nombre de parts : **{calcul.get('nombre_parts', '?')}**\n"
            text += f"- Quotient familial : **{fmt(calcul.get('quotient_familial', 0))}**\n"
            text += f"- Impôt brut : **{fmt(calcul.get('impot_brut', 0))}**\n"

            if calcul.get("decote"):
                text += f"- Décote : **- {fmt(calcul.get('decote', 0))}**\n"

            reductions = calcul.get("reductions", [])
            for r in reductions:
                if isinstance(r, dict):
                    text += f"- Réduction ({r.get('libelle', '?')}) : **- {fmt(r.get('montant', 0))}**\n"

            credits = calcul.get("credits", [])
            for c in credits:
                if isinstance(c, dict):
                    text += f"- Crédit d'impôt ({c.get('libelle', '?')}) : **- {fmt(c.get('montant', 0))}**\n"

            text += f"- **Impôt net : {fmt(calcul.get('impot_net', 0))}**\n"
            text += f"- Prélèvement à la source déjà payé : **- {fmt(calcul.get('prelev_source_deja_paye', 0))}**\n"

            solde = calcul.get("solde", 0)
            if isinstance(solde, (int, float)):
                if solde > 0:
                    text += f"\n**Solde à payer : {fmt(solde)}**\n"
                elif solde < 0:
                    text += f"\n**Remboursement estimé : {fmt(abs(solde))}**\n"
                else:
                    text += "\n**Aucun solde à payer ni remboursement.**\n"

            if calcul.get("detail_bareme"):
                text += f"\n*Détail du barème :* {calcul['detail_bareme']}\n"

        remarques = result.get("remarques", [])
        if remarques:
            text += "\n### Remarques\n"
            for r in remarques:
                text += f"- {r}\n"

        text += (
            "\n---\n"
            "*Ce calcul est une estimation. Vérifiez chaque montant avant de "
            "soumettre votre déclaration officielle sur impots.gouv.fr.*"
        )

        return text

    # ------------------------------------------------------------------
    # Validation des résultats
    # ------------------------------------------------------------------

    def _validate_result(self, result: dict) -> list[str]:
        """Valide la cohérence des résultats fiscaux."""
        warnings = []
        calcul = result.get("calcul_impot", {})

        rng = calcul.get("revenu_net_imposable", 0)
        rbg = calcul.get("revenu_brut_global", 0)
        if isinstance(rng, (int, float)) and isinstance(rbg, (int, float)):
            if rng > rbg > 0:
                warnings.append("Incohérence : le revenu net imposable est supérieur au revenu brut global.")

        impot_brut = calcul.get("impot_brut", 0)
        impot_net = calcul.get("impot_net", 0)
        if isinstance(impot_net, (int, float)) and impot_net < 0:
            warnings.append("L'impôt net est négatif — vérifiez les réductions et crédits d'impôt.")

        parts = result.get("situation", {}).get("parts", 1.0)
        if isinstance(parts, (int, float)):
            valid_parts = {x * 0.25 for x in range(2, 41)}  # 0.5, 0.75, 1.0, ..., 10.0
            if parts not in valid_parts:
                warnings.append(f"Le nombre de parts ({parts}) semble inhabituel — vérifiez la situation familiale.")

        # Vérifier que les cases déclarées existent dans le référentiel
        known_cases = set(self.rag.get_all_cases())
        if known_cases:
            for c in result.get("cases", []):
                case_num = c.get("case", "")
                if case_num and case_num not in known_cases:
                    warnings.append(f"La case {case_num} n'est pas dans le référentiel — vérifiez ce numéro.")

        return warnings

    # ------------------------------------------------------------------
    # Parsing JSON robuste
    # ------------------------------------------------------------------

    def _parse_llm_json(self, text: str) -> dict | None:
        """Extrait du JSON depuis la réponse du LLM, avec nettoyage."""
        if not text or text.startswith("ERREUR"):
            print(f"[JSON] Texte vide ou erreur : {text[:200]}")
            return None

        # Stratégie 1 : JSON direct
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Stratégie 2 : Bloc ```json ... ```
        json_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError as e:
                print(f"[JSON] Bloc ```json trouvé mais invalide : {e}")

        # Stratégie 3 : Extraire le plus grand bloc { ... } valide
        best_result = None
        depth = 0
        start = -1
        for i, ch in enumerate(text):
            if ch == "{":
                if depth == 0:
                    start = i
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0 and start >= 0:
                    candidate = text[start:i + 1]
                    try:
                        parsed = json.loads(candidate)
                        # Garder le plus grand résultat valide
                        if best_result is None or len(candidate) > len(json.dumps(best_result)):
                            best_result = parsed
                    except json.JSONDecodeError:
                        pass
                    start = -1

        if best_result:
            print(f"[JSON] Extrait par recherche de bloc (taille : {len(json.dumps(best_result))} chars)")
            return best_result

        # Stratégie 4 : Nettoyage agressif et nouvelle tentative
        cleaned = text
        # Supprimer tout ce qui est avant le premier {
        first_brace = cleaned.find("{")
        if first_brace > 0:
            cleaned = cleaned[first_brace:]
        # Supprimer tout ce qui est après le dernier }
        last_brace = cleaned.rfind("}")
        if last_brace > 0:
            cleaned = cleaned[:last_brace + 1]
        # Corriger les erreurs courantes
        cleaned = cleaned.replace("'", '"')
        cleaned = re.sub(r",\s*}", "}", cleaned)  # Virgule trailing
        cleaned = re.sub(r",\s*]", "]", cleaned)  # Virgule trailing dans array

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        print(f"[JSON] ÉCHEC: impossible de parser. Début de réponse : {text[:300]}")
        return None

    # ------------------------------------------------------------------
    # Questions par défaut (fallback)
    # ------------------------------------------------------------------

    def _get_default_questions(self) -> list[str]:
        """Retourne les questions par défaut si le LLM n'en génère pas."""
        return [
            "Quelle est votre situation familiale au 31 décembre 2025 ? (célibataire, marié(e), pacsé(e), divorcé(e), veuf/veuve)",
            "Combien d'enfants avez-vous à charge ? (mineurs, ou majeurs rattachés de moins de 25 ans poursuivant leurs études)",
            "Vivez-vous seul(e) avec vos enfants ? (parent isolé — case T)",
            "Avez-vous des revenus autres que les salaires visibles dans les documents ? (revenus fonciers, micro-entreprise, dividendes, plus-values, RSU, etc.)",
            "Avez-vous effectué des versements sur un PER (Plan d'Épargne Retraite) ?",
            "Avez-vous effectué des dons à des associations ou organismes d'intérêt général ?",
            "Avez-vous employé un(e) salarié(e) à domicile ou avez-vous des frais de garde d'enfants de moins de 6 ans ?",
            "Êtes-vous propriétaire ou locataire de votre résidence principale ?",
        ]

    def _msg(self, content: str) -> dict:
        return {"type": "assistant", "content": content, "state": self.state}
