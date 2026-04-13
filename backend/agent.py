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
import asyncio
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
from extractors import extract_structured, extract_batch
from status_page import StatusPage

SYSTEM_PROMPT = (
    "Tu es un assistant fiscal expert en declaration d'impots francaise. "
    "IMPORTANT : Tu reponds TOUJOURS en francais. Jamais en anglais. "
    "Tu travailles UNIQUEMENT avec le profil fiscal JSON fourni. "
    "Tu reponds en JSON quand demande. Tu ne devines pas les informations manquantes. "
    "Toutes tes questions, explications et remarques sont en francais."
)

# Etats du pipeline
STATE_WELCOME = "welcome"
STATE_INGESTION = "ingestion"
STATE_PARALLEL = "parallel"  # Questions structurantes + ingestion en parallele
STATE_VALIDATION = "validation"
STATE_CALCUL = "calcul"
STATE_VERIFICATION = "verification"
STATE_DONE = "done"

# Patterns de noms de fichiers pour l'analyse rapide (sans LLM)
FILENAME_PATTERNS = {
    "salaire": {"keywords": ["paie", "salaire", "bulletin", "fiche_paie", "remuneration"], "category": "salaires"},
    "impot": {"keywords": ["impot", "imposition", "2042", "avis_ir", "declaration"], "category": "impots"},
    "foncier": {"keywords": ["foncier", "taxe_fonciere", "tf_", "fonciere"], "category": "immobilier"},
    "pret": {"keywords": ["pret", "emprunt", "credit", "echeancier", "amortissement"], "category": "immobilier"},
    "bail": {"keywords": ["bail", "contrat_location", "quittance", "loyer"], "category": "immobilier"},
    "assurance": {"keywords": ["assurance", "attestation", "maif", "axa", "allianz", "cotisation_habitation", "pno"], "category": "assurance"},
    "banque": {"keywords": ["releve", "bancaire", "compte", "banque", "transatlantique", "boursorama", "bnp", "sg"], "category": "banque"},
    "titre": {"keywords": ["titre", "ifu", "portefeuille", "action", "dividende", "easybourse", "bourse"], "category": "titres"},
    "scpi": {"keywords": ["scpi", "corum", "immorente", "primovie"], "category": "scpi"},
    "sci": {"keywords": ["sci", "societe_civile", "bilan_sci", "2072"], "category": "sci"},
    "societe": {"keywords": ["societe", "sasu", "sarl", "sas", "bilan", "liasse", "2065"], "category": "societe"},
    "rsu": {"keywords": ["rsu", "stock", "option", "vesting", "acquisition", "gains_acquisition"], "category": "titres"},
    "don": {"keywords": ["don", "recu_fiscal", "association", "cerfa"], "category": "deductions"},
    "garde": {"keywords": ["garde", "creche", "nourrice", "pajemploi"], "category": "deductions"},
    "retraite": {"keywords": ["retraite", "pension", "cnav", "agirc", "arrco", "per_"], "category": "retraite"},
}


class AgentFiscal:
    def __init__(self, document_parser: DocumentParser, fiscal_engine: FiscalEngine,
                 report_generator: ReportGenerator, session_id: str = "",
                 output_dir: str = ""):
        self.parser = document_parser
        self.engine = fiscal_engine
        self.reporter = report_generator
        self.rag = FiscalRAG()
        self.session_id = session_id

        # Memoire persistante
        self.store = SessionStore(session_id) if session_id else None
        self.profile = FiscalProfile(session_id) if session_id else None
        self.extractions = ExtractionStore(session_id) if session_id else None

        # Page de status HTML temps reel
        self.status = StatusPage(output_dir or str(Path(__file__).resolve().parent.parent / "output"), session_id) if session_id else None

        # Callbacks pour envoyer des messages en temps reel (set par app.py)
        self.on_progress = None
        self.on_send = None

        # Ingestion en arriere-plan (pendant que l'utilisateur repond aux questions)
        self._ingestion_task: asyncio.Task | None = None
        self._ingestion_done = False
        self._files_to_ingest: list[Path] = []

        # Etat courant
        self._restore_state()

    def _restore_state(self):
        """Restaure l'etat depuis la memoire persistante."""
        if self.store and not self.store.is_new():
            self.state = self.store.get("state", STATE_WELCOME)
            self.documents_path = self.store.get("documents_path", "")
            self.conversation_history = self.store.get_history()
            self.pending_questions = self.store.get("pending_questions", [])
            self.current_question_index = self.store.get("current_question_index", 0)

            # Verifier s'il reste des documents non extraits
            # Si oui, forcer l'etat a "ingestion" pour reprendre
            if self.documents_path and self.state not in (STATE_WELCOME, STATE_DONE):
                remaining = self._count_remaining_docs()
                if remaining > 0:
                    print(f"[SESSION] {remaining} documents non extraits detectes, forcage etat -> ingestion")
                    self.state = STATE_INGESTION
                    self.store.set("state", STATE_INGESTION)

            print(f"[SESSION] Restauree : etat={self.state}, profil completude={self.profile.get_completeness():.0%}")
        else:
            self.state = STATE_WELCOME
            self.documents_path = ""
            self.conversation_history = []
            self.pending_questions = []
            self.current_question_index = 0
            if self.store:
                self.store.init_session()

    def _count_remaining_docs(self) -> int:
        """Compte les documents dans le dossier qui n'ont pas encore ete extraits."""
        if not self.documents_path:
            return 0
        folder = Path(self.documents_path)
        if not folder.exists():
            return 0
        supported_ext = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".xlsx", ".xls", ".csv", ".docx", ".txt"}
        all_files = {f.name for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in supported_ext}
        already_done = {e.get("doc_id") for e in self.extractions.get_all()} if self.extractions else set()
        return len(all_files - already_done)

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
            responses = await self._resume_ingestion()
        elif self.state == STATE_PARALLEL:
            responses = await self._handle_parallel_answer(user_message)
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

        # Envoyer le pourcentage de completion apres chaque echange
        await self._send_completion()

        return responses

    # ==================================================================
    # Étape 0 : Démarrage — choix du dossier
    # ==================================================================

    def _looks_like_path(self, text: str) -> bool:
        """Detecte si le texte ressemble a un chemin de fichier."""
        text = text.strip().strip('"').strip("'")
        # Un chemin contient generalement \ ou / et pas d'espace en debut
        if re.match(r"^[A-Za-z]:\\", text):    # C:\Users\...
            return True
        if re.match(r"^/[a-zA-Z]", text):      # /home/user/... ou /c/Users/...
            return True
        if re.match(r"^~[/\\]", text):          # ~/Documents/...
            return True
        if re.match(r"^\.", text) and ("/" in text or "\\" in text):  # ./dossier
            return True
        return False

    async def _step_start(self, user_input: str) -> list[dict]:
        # Detecter si c'est un chemin ou une phrase conversationnelle
        if not self._looks_like_path(user_input):
            return [self._msg(
                "Je comprends que vous souhaitez faire votre declaration d'impots !\n\n"
                "Avant de commencer, j'ai besoin que vous prepariez un **dossier sur votre PC** "
                "contenant tous vos documents fiscaux. Voici comment faire :\n\n"
                "### 1. Creez un dossier\n"
                "Par exemple : `C:\\Users\\VotreNom\\Documents\\Impots2025`\n\n"
                "### 2. Rassemblez-y vos documents\n"
                "Organisez-les si possible en sous-dossiers :\n"
                "```\n"
                "Impots2025/\n"
                "  salaires/          <- bulletins de paie (PDF)\n"
                "  immobilier/        <- taxes foncieres, baux, prets\n"
                "  banque/            <- releves, IFU, dividendes\n"
                "  assurance/         <- attestations habitation, PNO\n"
                "  societe/           <- bilans SCI/SCPI, liasses\n"
                "  divers/            <- dons, factures, attestations\n"
                "```\n\n"
                "### 3. Formats acceptes\n"
                "PDF, PNG, JPG, Excel (.xlsx), CSV, Word (.docx), TXT\n\n"
                "### 4. Donnez-moi le chemin\n"
                "Une fois le dossier pret, collez ici le chemin complet, par exemple :\n\n"
                "`C:\\Users\\VotreNom\\Documents\\Impots2025`\n\n"
                "J'analyserai chaque document automatiquement pour construire votre profil fiscal."
            )]

        folder_path = user_input.strip().strip('"').strip("'")
        folder = Path(folder_path)

        if not folder.exists():
            return [self._msg(
                f"Le dossier `{folder_path}` n'existe pas.\n\n"
                "Verifiez le chemin et reessayez. Le chemin doit etre complet, par exemple :\n"
                "`C:\\Users\\VotreNom\\Documents\\Impots2025`"
            )]
        if not folder.is_dir():
            return [self._msg(f"`{folder_path}` n'est pas un dossier.")]

        self.documents_path = str(folder)

        # Scanner les fichiers
        supported_ext = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".xlsx", ".xls", ".csv", ".docx", ".txt"}
        files = [f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in supported_ext]

        if not files:
            return [self._msg(f"Aucun document exploitable dans `{folder_path}`.\n\nFormats : PDF, PNG, JPG, XLSX, CSV, DOCX, TXT.")]

        self._files_to_ingest = files

        # === ANALYSE RAPIDE DES NOMS DE FICHIERS (instantanee, sans LLM) ===
        quick_analysis = self._analyze_filenames(files, folder)

        file_list = "\n".join(f"  - `{f.relative_to(folder)}`" for f in files[:30])
        if len(files) > 30:
            file_list += f"\n  - ... et {len(files) - 30} autre(s)"

        # Generer les questions structurantes basees sur les types detectes
        preliminary_questions = self._generate_preliminary_questions(quick_analysis)
        self.pending_questions = preliminary_questions
        self.current_question_index = 0

        # Passer en mode parallele : questions + ingestion simultanees
        self.state = STATE_PARALLEL
        self._ingestion_done = False
        self._persist()

        if self.status:
            self.status.set_state("parallel")

        # Envoyer le resume de l'analyse rapide
        categories_found = quick_analysis.get("categories", {})
        cat_summary = ""
        if categories_found:
            cat_summary = "**Types de documents detectes (analyse rapide) :**\n"
            for cat, cat_files in categories_found.items():
                cat_summary += f"- {cat} : {len(cat_files)} fichier(s)\n"
            cat_summary += "\n"

        await self._send_now(
            f"**{len(files)} document(s)** trouves :\n\n{file_list}\n\n"
            f"{cat_summary}"
            "L'analyse approfondie de chaque document demarre **en arriere-plan**.\n"
            "En attendant, je vais vous poser quelques questions pour mieux comprendre votre situation.\n"
        )

        # Lancer l'ingestion en arriere-plan
        self._ingestion_task = asyncio.create_task(
            self._background_ingestion(files, folder)
        )

        # Poser la premiere question immediatement
        if self.pending_questions:
            total = len(self.pending_questions)
            return [self._msg(
                f"**Question 1/{total}** :\n{self.pending_questions[0]}"
            )]

        # Pas de questions (cas improbable) -> attendre l'ingestion
        self.state = STATE_INGESTION
        self._persist()
        return [self._msg("Analyse des documents en cours...")]

    # ==================================================================
    # Analyse rapide des noms de fichiers (instantanee, sans LLM)
    # ==================================================================

    def _analyze_filenames(self, files: list[Path], folder: Path) -> dict:
        """Analyse les noms de fichiers pour detecter les types de documents."""
        categories: dict[str, list[str]] = {}
        detected_types: set[str] = set()

        for f in files:
            name_lower = f.name.lower().replace("-", "_").replace(" ", "_")
            matched = False
            for doc_type, info in FILENAME_PATTERNS.items():
                for keyword in info["keywords"]:
                    if keyword in name_lower:
                        cat = info["category"]
                        categories.setdefault(cat, []).append(f.name)
                        detected_types.add(doc_type)
                        matched = True
                        break
                if matched:
                    break
            if not matched:
                categories.setdefault("autres", []).append(f.name)

        print(f"[QUICK] Analyse rapide : {len(detected_types)} types detectes sur {len(files)} fichiers")
        for cat, cat_files in categories.items():
            print(f"[QUICK]   {cat}: {len(cat_files)} fichier(s)")

        return {"categories": categories, "detected_types": detected_types}

    def _generate_preliminary_questions(self, quick_analysis: dict) -> list[str]:
        """Genere des questions structurantes basees sur les types de documents detectes.
        Ne pose PAS les questions dont la reponse est deja dans le profil."""
        questions = []
        types = quick_analysis.get("detected_types", set())
        categories = quick_analysis.get("categories", {})
        foyer = self.profile.data.get("foyer", {}) if self.profile else {}

        # Questions universelles — seulement si pas deja dans le profil
        if not foyer.get("situation"):
            questions.append(
                "Quelle est votre situation familiale au 31/12/2025 ? "
                "(celibataire, marie(e), pacse(e), divorce(e), veuf/veuve)"
            )
        if foyer.get("nb_enfants_mineurs", 0) == 0 and not foyer.get("situation"):
            # Demander les enfants seulement si la situation n'est pas connue non plus
            questions.append(
                "Combien d'enfants avez-vous a charge ? "
                "(mineurs, ou majeurs rattaches de moins de 25 ans en etudes)"
            )

        # Questions adaptees aux documents detectes
        if "immobilier" in categories:
            questions.append(
                "Concernant vos biens immobiliers :\n"
                "- Combien de biens possedez-vous ?\n"
                "- Pour chaque bien loue : est-ce de la location nue (bail 3 ans) ou meublee (LMNP/Airbnb) ?\n"
                "- Etes-vous au regime micro-foncier ou reel ?"
            )

        if "titres" in categories or "rsu" in types:
            questions.append(
                "Concernant vos revenus de placements :\n"
                "- Avez-vous des RSU (Restricted Stock Units) ou stock-options ? Si oui, de quelle societe ?\n"
                "- Avez-vous un PEA ?\n"
                "- Preferez-vous le prelevement forfaitaire (flat tax 30%) ou l'option bareme ?"
            )

        if "societe" in categories or "sci" in categories or "scpi" in categories:
            questions.append(
                "Concernant vos societes :\n"
                "- Quel type de societe ? (SCI, SCPI, SASU, SARL, SAS, EURL...)\n"
                "- Regime fiscal : IR (transparence) ou IS ?\n"
                "- Etes-vous gerant/president ? Recevez-vous une remuneration et/ou des dividendes ?"
            )

        if "salaire" in types:
            questions.append(
                "Pour vos salaires :\n"
                "- Avez-vous opte pour les frais reels (au lieu de l'abattement 10%) ?\n"
                "- Avez-vous des heures supplementaires exonerees ?"
            )

        if "retraite" in types:
            questions.append(
                "Percevez-vous une pension de retraite, d'invalidite ou une rente ?"
            )

        # Questions generales (si pas trop de questions deja)
        if len(questions) < 6:
            questions.append(
                "Avez-vous des charges deductibles ?\n"
                "- Dons a des associations\n"
                "- Emploi a domicile (menage, garde d'enfants)\n"
                "- Versements sur un PER (Plan Epargne Retraite)\n"
                "- Pension alimentaire versee"
            )

        return questions

    # ==================================================================
    # Mode parallele : questions + ingestion en arriere-plan
    # ==================================================================

    async def _background_ingestion(self, files: list[Path], folder: Path):
        """Lance l'ingestion en arriere-plan (pendant que l'utilisateur repond aux questions)."""
        try:
            print(f"[BACKGROUND] Demarrage ingestion de {len(files)} documents en arriere-plan")
            await self._run_ingestion(files, folder)
            self._ingestion_done = True
            print(f"[BACKGROUND] Ingestion terminee")
        except Exception as e:
            print(f"[BACKGROUND] Erreur ingestion : {e}")
            self._ingestion_done = True  # Marquer comme done meme en cas d'erreur

    async def _handle_parallel_answer(self, answer: str) -> list[dict]:
        """Gere les reponses pendant que l'ingestion tourne en arriere-plan."""
        # Enregistrer la reponse
        if self.current_question_index < len(self.pending_questions):
            question = self.pending_questions[self.current_question_index]

            # Structurer la reponse dans le profil
            extraction = await self._structure_answer(question, answer)
            if extraction:
                self.profile.merge_user_answers(extraction)

            # Mettre a jour le status
            if self.status:
                self.status.add_question(question, answer)
                self.status.set_profile(self.profile.data)

            self.current_question_index += 1
            self._persist()

        # Encore des questions ?
        if self.current_question_index < len(self.pending_questions):
            total = len(self.pending_questions)
            idx = self.current_question_index

            # Indiquer la progression de l'ingestion en arriere-plan
            already_done = len(self.extractions.get_all()) if self.extractions else 0
            total_files = len(self._files_to_ingest)
            bg_status = ""
            if not self._ingestion_done and total_files > 0:
                bg_status = f"\n\n*Analyse en arriere-plan : {already_done}/{total_files} documents traites...*"

            return [self._msg(
                f"**Question {idx + 1}/{total}** :\n{self.pending_questions[idx]}{bg_status}"
            )]

        # Toutes les questions repondues -- attendre la fin de l'ingestion si necessaire
        if not self._ingestion_done:
            # Attendre l'ingestion avec un message
            await self._send_now("Merci pour vos reponses ! L'analyse des documents est encore en cours...")

            if self._ingestion_task:
                await self._ingestion_task  # Attendre la fin

            await self._send_now("Analyse terminee !")

        # Construire le profil depuis les extractions
        if self.extractions and self.profile:
            profile_data = self.extractions.build_profile_data()
            self.profile.merge_extraction(profile_data, "extraction_store")
            self.profile.save()

        # Afficher le resume
        summary = self.extractions.get_summary() if self.extractions else {}
        completeness = self.profile.get_completeness() if self.profile else 0
        profile_preview = self.profile.get_for_llm() if self.profile else "{}"

        msg = f"**Profil fiscal construit** (completude : {completeness:.0%})\n\n"
        if summary.get("montants_cles"):
            msg += "**Montants cles extraits :**\n"
            for key, val in summary["montants_cles"].items():
                msg += f"- {key} : {val:,.2f} EUR\n"
            msg += "\n"

        # Passer a la validation (questions complementaires basees sur le profil complet)
        self.state = STATE_VALIDATION
        self._persist()

        validation_responses = await self._step_validation_detect_missing()
        return [self._msg(msg)] + validation_responses

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

    def _compute_completion(self) -> int:
        """Calcule le pourcentage de completion de la session."""
        if self.state == "done":
            return 100

        # Compter les fichiers totaux
        total_files = 0
        if self.documents_path:
            folder = Path(self.documents_path)
            if folder.exists():
                exts = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".xlsx", ".xls", ".csv", ".docx", ".txt"}
                total_files = len([f for f in folder.rglob("*") if f.is_file() and f.suffix.lower() in exts])

        docs_extracted = len(self.extractions.get_all()) if self.extractions else 0
        ingestion_pct = docs_extracted / total_files if total_files > 0 else 0

        if self.state in (STATE_WELCOME, STATE_INGESTION):
            return int(ingestion_pct * 50)

        if self.state == STATE_PARALLEL:
            q_total = len(self.pending_questions)
            q_done = self.current_question_index
            q_pct = q_done / q_total if q_total > 0 else 0
            return int(ingestion_pct * 35 + q_pct * 15)

        if self.state == STATE_VALIDATION:
            q_total = len(self.pending_questions)
            q_done = self.current_question_index
            q_pct = q_done / q_total if q_total > 0 else 1.0
            return 50 + int(q_pct * 25)

        if self.state == STATE_CALCUL:
            return 85
        if self.state == STATE_VERIFICATION:
            return 95

        return 0

    async def _send_completion(self):
        """Envoie le pourcentage de completion au frontend."""
        pct = self._compute_completion()
        if self.on_progress:
            try:
                await self.on_progress({"type": "completion", "percent": pct})
            except Exception:
                pass

    async def _send_progress(self, msg: dict):
        """Envoie un message de progression en temps reel via le WebSocket + status page."""
        if self.on_progress:
            try:
                await self.on_progress(msg)
            except Exception:
                pass
        # Envoyer le pourcentage mis a jour
        await self._send_completion()
        # Mettre a jour la page de status
        if self.status and msg.get("filename"):
            self.status.add_document(
                msg["filename"],
                msg.get("status", "?"),
                msg.get("detail", "").split("|")[0].strip() if "|" in msg.get("detail", "") else "",
                msg.get("detail", ""),
            )

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

    async def _run_ingestion(self, files: list[Path], folder: Path):
        """Boucle d'extraction avec batching des petits documents."""
        total = len(files)
        already_done = {e.get("doc_id") for e in self.extractions.get_all()} if self.extractions else set()

        # Separer les fichiers a traiter en 2 groupes : petits (batchables) et gros
        BATCH_CONTENT_LIMIT = 1500  # chars — en dessous, on batch
        BATCH_SIZE = 3  # docs par batch

        pending_batch: list[dict] = []  # [{"filename", "content", "index"}]
        processed = 0

        for i, f in enumerate(files):
            filename = f.name
            pct = int(((processed) / total) * 100) if total else 0

            if filename in already_done:
                processed += 1
                await self._send_progress({
                    "type": "progress", "current": processed, "total": total,
                    "percent": int((processed / total) * 100), "filename": filename,
                    "status": "skip", "detail": "Deja traite",
                })
                continue

            # Parser le document
            doc_data = self.parser.parse(str(f))
            if not doc_data or not doc_data.get("content"):
                processed += 1
                await self._send_progress({
                    "type": "progress", "current": processed, "total": total,
                    "percent": int((processed / total) * 100), "filename": filename,
                    "status": "error", "detail": "Contenu non extractible",
                })
                continue

            content = doc_data["content"]

            # Petit document -> ajouter au batch
            if len(content) <= BATCH_CONTENT_LIMIT:
                pending_batch.append({"filename": filename, "content": content, "index": i})

                # Lancer le batch quand il est plein
                if len(pending_batch) >= BATCH_SIZE:
                    processed = await self._flush_batch(pending_batch, processed, total)
                    pending_batch = []
                continue

            # Gros document -> extraction individuelle
            await self._send_progress({
                "type": "progress", "current": processed + 1, "total": total,
                "percent": int((processed / total) * 100), "filename": filename,
                "status": "processing", "detail": "Extraction en cours...",
            })

            extraction = await extract_structured(filename, content)
            processed += 1

            if extraction:
                self.extractions.add(extraction)
                doc_type = extraction.get("type_document", "?")
                montants = extraction.get("montants", {})
                detail = doc_type + (f" | {', '.join(montants.keys())}" if montants else "")
                await self._send_progress({
                    "type": "progress", "current": processed, "total": total,
                    "percent": int((processed / total) * 100), "filename": filename,
                    "status": "ok", "detail": detail,
                })
            else:
                await self._send_progress({
                    "type": "progress", "current": processed, "total": total,
                    "percent": int((processed / total) * 100), "filename": filename,
                    "status": "error", "detail": "Extraction echouee",
                })

        # Flush le dernier batch partiel
        if pending_batch:
            processed = await self._flush_batch(pending_batch, processed, total)

        # Embeddings en une seule passe a la fin
        if self.extractions:
            self.extractions.finalize_embeddings()

    async def _flush_batch(self, batch: list[dict], processed: int, total: int) -> int:
        """Traite un batch de petits documents en un seul appel LLM."""
        filenames = [d["filename"] for d in batch]
        batch_label = ", ".join(filenames[:3])
        if len(filenames) > 3:
            batch_label += f"... (+{len(filenames)-3})"

        await self._send_progress({
            "type": "progress", "current": processed + 1, "total": total,
            "percent": int((processed / total) * 100) if total else 0,
            "filename": f"[Batch: {len(batch)} docs]",
            "status": "processing", "detail": batch_label,
        })

        results = await extract_batch(batch)

        for j, result in enumerate(results):
            processed += 1
            fname = batch[j]["filename"]
            if result:
                self.extractions.add(result)
                doc_type = result.get("type_document", "?")
                await self._send_progress({
                    "type": "progress", "current": processed, "total": total,
                    "percent": int((processed / total) * 100),
                    "filename": fname, "status": "ok", "detail": doc_type,
                })
            else:
                await self._send_progress({
                    "type": "progress", "current": processed, "total": total,
                    "percent": int((processed / total) * 100),
                    "filename": fname, "status": "error", "detail": "Extraction echouee",
                })

        return processed

    async def _step_ingestion(self, files: list[Path], folder: Path) -> list[dict]:
        """Ingestion complete (mode foreground, pour la reprise)."""
        await self._send_now("Reprise de l'analyse des documents...")
        await self._run_ingestion(files, folder)

        # Construire le profil
        if self.extractions and self.profile:
            profile_data = self.extractions.build_profile_data()
            self.profile.merge_extraction(profile_data, "extraction_store")
            self.profile.save()

        summary = self.extractions.get_summary() if self.extractions else {}
        completeness = self.profile.get_completeness() if self.profile else 0

        msg = f"**Analyse terminee** ({summary.get('nb_documents', 0)} documents)\n\n"
        if summary.get("montants_cles"):
            msg += "**Montants cles :**\n"
            for key, val in summary["montants_cles"].items():
                msg += f"- {key} : {val:,.2f} EUR\n"
            msg += "\n"

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

        # Construire la liste de ce qui est DEJA connu pour eviter les questions redondantes
        already_known = []
        foyer = self.profile.data.get("foyer", {}) if self.profile else {}
        if foyer.get("situation"):
            already_known.append(f"situation familiale: {foyer['situation']}")
        if foyer.get("nb_enfants_mineurs", 0) > 0:
            already_known.append(f"enfants a charge: {foyer['nb_enfants_mineurs']}")
        for note in (self.profile.data.get("notes", []) if self.profile else []):
            if isinstance(note, str) and len(note) < 100:
                already_known.append(note)

        known_text = "\n".join(f"- {k}" for k in already_known) if already_known else "(rien)"

        prompt = (
            f"## Referentiel fiscal\n{rag_context}\n\n"
            f"## Profil fiscal actuel du contribuable\n```json\n{profile_json}\n```\n\n"
            f"## Informations DEJA CONNUES (ne PAS redemander)\n{known_text}\n\n"
            "## Mission\n\n"
            "IMPORTANT : Reponds UNIQUEMENT en francais.\n\n"
            "Analyse ce profil fiscal et identifie les informations MANQUANTES "
            "pour pouvoir calculer l'impot. Genere des questions PRECISES pour les obtenir.\n\n"
            "Regles STRICTES :\n"
            "- Toutes les questions en FRANCAIS\n"
            "- Ne JAMAIS redemander ce qui est deja dans le profil ou dans les infos connues ci-dessus\n"
            "- La situation familiale et le nombre d'enfants sont deja connus si presents dans le profil\n"
            "- Priorise : regime foncier (si foncier detecte), credits d'impot, charges deductibles\n"
            "- Maximum 8 questions\n"
            "- Si le profil est suffisant pour calculer, retourne un tableau vide\n\n"
            "Reponds en JSON :\n"
            "```json\n"
            '{"missing": [], "questions": []}\n'
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
        """Traite une reponse et met a jour le profil."""
        if self.current_question_index < len(self.pending_questions):
            question = self.pending_questions[self.current_question_index]

            extraction = await self._structure_answer(question, answer)
            if extraction:
                self.profile.merge_user_answers(extraction)

            if self.status:
                self.status.add_question(question, answer)
                self.status.set_profile(self.profile.data)
                self.status.set_state("validation")

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
        """Transforme une reponse en donnees structurees. Pattern matching LOCAL d'abord, LLM en fallback."""
        # Essayer le pattern matching local (instantane, pas d'appel LLM)
        local_result = self._structure_answer_local(question, answer)
        if local_result:
            print(f"[ANSWER] Structure localement (pas d'appel LLM)")
            return local_result

        # Fallback LLM pour les reponses complexes
        print(f"[ANSWER] Reponse complexe, appel LLM...")
        prompt = (
            f"Question : {question}\n"
            f"Reponse de l'utilisateur : {answer}\n\n"
            "Transforme cette reponse en JSON partiel pour un profil fiscal francais.\n"
            "Les valeurs texte doivent etre en francais.\n"
            "Cles possibles : foyer.situation, foyer.nb_enfants_mineurs, foyer.parent_isole, "
            "revenus.foncier_nu, revenus.foncier_meuble, charges_deductibles, reductions_credits\n\n"
            '```json\n{"foyer": {"situation": "marie", "nb_enfants_mineurs": 2}}\n```'
        )
        response = await query_llm(prompt, SYSTEM_PROMPT, temperature=0.1, max_tokens=500)
        return _parse_json(response)

    def _structure_answer_local(self, question: str, answer: str) -> dict | None:
        """Pattern matching local pour les reponses courantes (instantane)."""
        q = question.lower()
        a = answer.lower().strip()

        # --- Situation familiale ---
        if "situation familiale" in q:
            result = {"foyer": {}}
            if any(w in a for w in ("marie", "marié", "mariee", "mariée")):
                result["foyer"]["situation"] = "marie"
            elif any(w in a for w in ("pacse", "pacsé", "pacsee", "pacsée", "pacs")):
                result["foyer"]["situation"] = "pacse"
            elif any(w in a for w in ("divorce", "divorcé", "divorcee", "divorcée", "separe")):
                result["foyer"]["situation"] = "divorce"
            elif any(w in a for w in ("veuf", "veuve")):
                result["foyer"]["situation"] = "veuf"
            elif any(w in a for w in ("celibataire", "célibataire", "seul")):
                result["foyer"]["situation"] = "celibataire"
            # Chercher le nombre d'enfants dans la meme reponse
            nb = re.search(r"(\d+)\s*enfant", a)
            if nb:
                result["foyer"]["nb_enfants_mineurs"] = int(nb.group(1))
            if result["foyer"]:
                return result

        # --- Nombre d'enfants ---
        if "enfant" in q:
            nb = re.search(r"(\d+)", a)
            if nb:
                return {"foyer": {"nb_enfants_mineurs": int(nb.group(1))}}
            if any(w in a for w in ("aucun", "pas d", "0", "non", "zero")):
                return {"foyer": {"nb_enfants_mineurs": 0}}

        # --- Frais reels ---
        if "frais" in q and "reel" in q:
            if any(w in a for w in ("oui", "reel", "réel", "réels")):
                return {"notes": ["Option frais reels"]}
            if any(w in a for w in ("non", "10%", "abattement", "forfait")):
                return {"notes": ["Abattement forfaitaire 10%"]}

        # --- Regime foncier ---
        if "micro" in q and "foncier" in q or "regime" in q and "foncier" in q:
            if any(w in a for w in ("micro", "micro-foncier")):
                return {"notes": ["Regime micro-foncier"]}
            if any(w in a for w in ("reel", "réel")):
                return {"notes": ["Regime reel foncier"]}

        # --- Location nue vs meublee ---
        if "location" in q or "meuble" in q or "lmnp" in q:
            result = {"notes": []}
            if any(w in a for w in ("nue", "nu ", "bail 3 ans", "non meuble")):
                result["notes"].append("Location nue (bail 3 ans)")
            if any(w in a for w in ("meuble", "meublé", "lmnp", "airbnb", "saisonni")):
                result["notes"].append("Location meublee (LMNP)")
            nb = re.search(r"(\d+)\s*(?:bien|appart|logement|maison)", a)
            if nb:
                result["notes"].append(f"{nb.group(1)} bien(s) locatif(s)")
            if result["notes"]:
                return result

        # --- PEA / flat tax ---
        if "pea" in q or "flat tax" in q or "bareme" in q:
            if any(w in a for w in ("pfu", "flat", "forfaitaire", "30%")):
                return {"revenus": {"capitaux_mobiliers": {"option_bareme": False}}}
            if any(w in a for w in ("bareme", "barème", "progressif")):
                return {"revenus": {"capitaux_mobiliers": {"option_bareme": True}}}

        # --- Reponses oui/non simples ---
        if any(w in a for w in ("non", "pas ", "aucun", "rien", "0")):
            return {"notes": [f"Reponse: non a '{question[:60]}'"]}
        if a in ("oui", "yes"):
            return {"notes": [f"Reponse: oui a '{question[:60]}'"]}

        # Pas de match local -> fallback LLM
        return None

    # ==================================================================
    # Étape 3 : CALCUL — RAG + profil JSON -> cases 2042
    # ==================================================================

    async def _step_calcul(self) -> list[dict]:
        """Calcul fiscal base UNIQUEMENT sur le profil JSON + RAG."""
        if self.status:
            self.status.set_state("calcul")
            self.status.set_profile(self.profile.data)

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
            "# INSTRUCTIONS (reponds en FRANCAIS uniquement)\n\n"
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

        # Sauvegarder le resultat
        if self.store:
            self.store.save_result(result)

        # Mettre a jour le status avec les resultats
        if self.status:
            self.status.set_cases(result.get("cases", []))
            self.status.set_calcul(result.get("calcul_impot", {}))
            self.status.set_warnings(result.get("remarques", []))
            self.status.set_state("verification")

        # Generer le rapport
        report_path = self.reporter.generate(result, [], profile)

        if self.store:
            self.store.set("report_path", report_path)

        if self.status:
            self.status.set_report_path(report_path)
            self.status.set_state("done")

        self.state = STATE_DONE
        self._persist()

        summary = self._build_result_summary(result)

        return [
            self._msg(summary),
            {
                "type": "report",
                "content": "Le rapport detaille a ete sauvegarde.",
                "report_html": f"{report_path}.html",
                "report_pdf": f"{report_path}.pdf",
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
            remaining = self._count_remaining_docs()
            msg += f"{already_extracted} document(s) deja analyse(s), **{remaining} restant(s)**.\n\n"
            msg += "Tapez **ok** pour reprendre l'analyse et lancer le calcul."

        elif self.state == STATE_PARALLEL:
            q_done = self.current_question_index
            q_total = len(self.pending_questions)
            msg += f"{already_extracted} document(s) deja analyse(s). "
            msg += f"{q_done}/{q_total} questions repondues.\n\n"
            # Relancer l'ingestion en arriere-plan et reprendre les questions
            msg += "L'analyse des documents va reprendre en arriere-plan.\n"
            if q_done < q_total:
                msg += f"\n**Question {q_done + 1}/{q_total}** :\n{self.pending_questions[q_done]}"
            else:
                msg += "Tapez **ok** pour continuer."

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
        """Genere des questions par defaut basees sur les trous du profil.
        Ne pose JAMAIS une question dont la reponse est deja dans le profil."""
        questions = []
        p = self.profile.data
        foyer = p.get("foyer", {})
        revenus = p.get("revenus", {})

        if not foyer.get("situation"):
            questions.append("Quelle est votre situation familiale au 31/12/2025 ? (celibataire, marie(e), pacse(e), divorce(e), veuf/veuve)")
        if foyer.get("nb_enfants_mineurs", 0) == 0 and not foyer.get("situation"):
            questions.append("Combien d'enfants avez-vous a charge ? (mineurs, ou majeurs rattaches < 25 ans)")
        if not revenus.get("salaires") and not revenus.get("pensions_retraite"):
            questions.append("Quels sont vos revenus principaux ? (salaires, pensions, etc.)")
        if revenus.get("foncier_nu") and not any(f.get("regime") for f in revenus["foncier_nu"]):
            questions.append("Pour vos revenus fonciers, etes-vous au regime micro-foncier ou au regime reel ?")
        if revenus.get("foncier_meuble") and not any(f.get("regime") for f in revenus["foncier_meuble"]):
            questions.append("Pour vos locations meublees, etes-vous au regime micro-BIC ou au regime reel ?")

        # Ne pas ajouter de questions generiques si le profil est deja bien rempli
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
