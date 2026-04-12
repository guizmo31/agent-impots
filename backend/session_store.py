"""
Mémoire persistante pour les sessions de déclaration d'impôts.

Sauvegarde automatiquement l'état complet de la session sur disque :
- Documents analysés et leur contenu extrait
- Profil fiscal (réponses aux questions)
- Historique de conversation
- État d'avancement (étape en cours)
- Notes et remarques ajoutées par l'agent
- Résultats de calcul (partiels ou finaux)

Chaque session est identifiée par un nom choisi par l'utilisateur
et stockée dans un fichier JSON dans le dossier sessions/.
"""
import json
from datetime import datetime
from pathlib import Path

SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
SESSIONS_DIR.mkdir(exist_ok=True)


class SessionStore:
    """Gère la persistance des sessions de déclaration."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.filepath = SESSIONS_DIR / f"{session_id}.json"
        self.data: dict = {}
        self._load()

    def _load(self):
        """Charge une session existante depuis le disque."""
        if self.filepath.exists():
            try:
                self.data = json.loads(self.filepath.read_text(encoding="utf-8"))
                print(f"[SESSION] Chargée : {self.session_id} (état: {self.data.get('state', '?')})")
            except (json.JSONDecodeError, OSError) as e:
                print(f"[SESSION] Erreur lecture {self.session_id}: {e}")
                self.data = {}

    def save(self):
        """Sauvegarde la session sur disque."""
        self.data["updated_at"] = datetime.now().isoformat()
        try:
            self.filepath.write_text(
                json.dumps(self.data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
        except OSError as e:
            print(f"[SESSION] Erreur écriture {self.session_id}: {e}")

    def is_new(self) -> bool:
        """Vérifie si c'est une nouvelle session."""
        return not self.data.get("created_at")

    def init_session(self, name: str = ""):
        """Initialise une nouvelle session."""
        self.data = {
            "session_id": self.session_id,
            "name": name or f"Déclaration {datetime.now().strftime('%d/%m/%Y')}",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
            "state": "welcome",
            "documents_path": "",
            "parsed_documents": [],
            "user_profile": {},
            "conversation_history": [],
            "pending_questions": [],
            "current_question_index": 0,
            "computation_result": None,
            "report_path": None,
            "notes": [],
        }
        self.save()

    # --- Getters / Setters avec auto-save ---

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value):
        self.data[key] = value
        self.save()

    def set_many(self, updates: dict):
        """Met à jour plusieurs clés d'un coup (un seul save)."""
        self.data.update(updates)
        self.save()

    # --- Conversation ---

    def add_message(self, role: str, content: str):
        """Ajoute un message à l'historique de conversation."""
        history = self.data.setdefault("conversation_history", [])
        history.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
        })
        # Pas de save ici — on le fait quand l'état change

    def get_history(self) -> list[dict]:
        return self.data.get("conversation_history", [])

    # --- Notes de l'agent ---

    def add_note(self, note: str):
        """Ajoute une note persistante (info importante détectée par l'agent)."""
        notes = self.data.setdefault("notes", [])
        notes.append({
            "content": note,
            "timestamp": datetime.now().isoformat(),
        })
        self.save()

    def get_notes(self) -> list[dict]:
        return self.data.get("notes", [])

    # --- Documents ---

    def save_documents(self, parsed_docs: list[dict]):
        """Sauvegarde les documents parsés (sans le contenu brut si trop gros)."""
        docs_to_save = []
        for doc in parsed_docs:
            # Stocker les métadonnées + contenu tronqué pour la session
            content = doc.get("content", "")
            docs_to_save.append({
                "filename": doc.get("filename", ""),
                "filepath": doc.get("filepath", ""),
                "extension": doc.get("extension", ""),
                "size_bytes": doc.get("size_bytes", 0),
                "content": content,  # Garder tout le contenu
                "content_length": len(content),
            })
        self.data["parsed_documents"] = docs_to_save
        self.save()

    def get_documents(self) -> list[dict]:
        return self.data.get("parsed_documents", [])

    # --- Profil fiscal ---

    def save_profile(self, profile: dict):
        self.data["user_profile"] = profile
        self.save()

    def get_profile(self) -> dict:
        return self.data.get("user_profile", {})

    # --- Résultat de calcul ---

    def save_result(self, result: dict):
        self.data["computation_result"] = result
        self.save()

    def get_result(self) -> dict | None:
        return self.data.get("computation_result")

    # --- Résumé pour affichage ---

    def get_summary(self) -> dict:
        """Retourne un résumé de la session pour l'UI."""
        return {
            "session_id": self.session_id,
            "name": self.data.get("name", "Sans nom"),
            "state": self.data.get("state", "welcome"),
            "created_at": self.data.get("created_at", ""),
            "updated_at": self.data.get("updated_at", ""),
            "documents_count": len(self.data.get("parsed_documents", [])),
            "questions_answered": self.data.get("current_question_index", 0),
            "questions_total": len(self.data.get("pending_questions", [])),
            "has_result": self.data.get("computation_result") is not None,
            "report_path": self.data.get("report_path"),
            "notes_count": len(self.data.get("notes", [])),
        }

    def delete(self):
        """Supprime la session du disque."""
        if self.filepath.exists():
            self.filepath.unlink()


def list_sessions() -> list[dict]:
    """Liste toutes les sessions existantes (uniquement les fichiers session principaux)."""
    sessions = []
    for f in SESSIONS_DIR.glob("*.json"):
        # Ignorer les fichiers auxiliaires (_extractions.json, _profile.json)
        if "_extractions" in f.name or "_profile" in f.name:
            continue

        try:
            data = json.loads(f.read_text(encoding="utf-8"))

            # Verifier que c'est bien un fichier de session (a un "state")
            if "state" not in data:
                continue

            session_id = f.stem

            # Compter les documents depuis le fichier _extractions.json
            docs_count = 0
            extractions_file = SESSIONS_DIR / f"{session_id}_extractions.json"
            if extractions_file.exists():
                try:
                    ext_data = json.loads(extractions_file.read_text(encoding="utf-8"))
                    docs_count = ext_data.get("count", len(ext_data.get("extractions", [])))
                except (json.JSONDecodeError, OSError):
                    pass

            sessions.append({
                "session_id": session_id,
                "name": data.get("name", "Sans nom"),
                "state": data.get("state", "?"),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
                "documents_count": docs_count,
                "has_result": data.get("computation_result") is not None,
            })
        except (json.JSONDecodeError, OSError):
            continue

    sessions.sort(key=lambda s: s.get("updated_at", ""), reverse=True)
    return sessions
