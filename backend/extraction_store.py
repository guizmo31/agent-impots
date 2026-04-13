"""
Store des extractions structurees du contribuable.

Stocke les extractions JSON sur disque. Pas d'embeddings (inutile
vu que le FiscalProfile JSON est la seule source de verite injectee
dans les prompts LLM).

Recherche par type, entite, ou mots-cles (sans LLM ni embedding).
"""
import json
from datetime import datetime
from pathlib import Path

SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"


class ExtractionStore:
    """Store persistant des extractions structurees."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.filepath = SESSIONS_DIR / f"{session_id}_extractions.json"
        self.extractions: list[dict] = []
        self._load()

    def _load(self):
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding="utf-8"))
                self.extractions = data.get("extractions", [])
            except (json.JSONDecodeError, OSError):
                self.extractions = []

    def save(self):
        data = {
            "session_id": self.session_id,
            "updated_at": datetime.now().isoformat(),
            "count": len(self.extractions),
            "extractions": self.extractions,
        }
        SESSIONS_DIR.mkdir(exist_ok=True)
        self.filepath.write_text(
            json.dumps(data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------
    # Ajout d'une extraction
    # ------------------------------------------------------------------

    def add(self, extraction: dict):
        """Ajoute une extraction et sauvegarde immediatement sur disque."""
        doc_id = extraction.get("doc_id", "")
        # Retirer le doublon eventuel
        self.extractions = [e for e in self.extractions if e.get("doc_id") != doc_id]
        self.extractions.append(extraction)
        self.save()

    # ------------------------------------------------------------------
    # Recherche
    # ------------------------------------------------------------------

    def search_by_type(self, doc_type: str) -> list[dict]:
        return [e for e in self.extractions if e.get("type_document", "").lower() == doc_type.lower()]

    def search_by_entity(self, entity_name: str) -> list[dict]:
        name_lower = entity_name.lower()
        return [e for e in self.extractions if name_lower in e.get("entite", {}).get("nom", "").lower()]

    def get_all(self) -> list[dict]:
        return self.extractions

    def get_summary(self) -> dict:
        types_count: dict[str, int] = {}
        total_montants: dict[str, float] = {}
        entities: set[str] = set()
        missing: list[str] = []

        for ext in self.extractions:
            doc_type = ext.get("type_document", "autre")
            types_count[doc_type] = types_count.get(doc_type, 0) + 1

            for key, val in ext.get("montants", {}).items():
                if isinstance(val, (int, float)) and val > 0:
                    total_montants[key] = total_montants.get(key, 0) + val

            entity = ext.get("entite", {}).get("nom", "")
            if entity:
                entities.add(entity)

            for m in ext.get("donnees_manquantes", []):
                if m not in missing:
                    missing.append(m)

        return {
            "nb_documents": len(self.extractions),
            "types": types_count,
            "montants_cles": total_montants,
            "entites": list(entities),
            "donnees_manquantes": missing,
        }

    def get_all_missing(self) -> list[str]:
        missing = []
        for ext in self.extractions:
            for m in ext.get("donnees_manquantes", []):
                if m not in missing:
                    missing.append(m)
        return missing

    # ------------------------------------------------------------------
    # Construction du profil fiscal
    # ------------------------------------------------------------------

    def build_profile_data(self) -> dict:
        """Construit les donnees du profil fiscal a partir des extractions."""
        profile = {"revenus": {}, "charges_deductibles": {}, "notes": []}

        for ext in self.extractions:
            doc_type = ext.get("type_document", "")
            montants = ext.get("montants", {})
            entite = ext.get("entite", {})
            doc_id = ext.get("doc_id", "")

            if doc_type == "fiche_de_paie":
                profile.setdefault("revenus", {}).setdefault("salaires", []).append({
                    "declarant": 1,
                    "source": entite.get("nom", "Employeur"),
                    "net_imposable": montants.get("net_imposable", 0),
                    "pas_retenu": montants.get("pas_retenu", montants.get("prelevement_source", 0)),
                    "heures_sup_exo": montants.get("heures_sup_exonerees", 0),
                    "doc_source": doc_id,
                })

            elif doc_type == "taxe_fonciere":
                profile.setdefault("revenus", {}).setdefault("foncier_nu", []).append({
                    "bien": entite.get("nom", montants.get("adresse_bien", "Bien immobilier")),
                    "taxe_fonciere_montant": montants.get("taxe_fonciere", montants.get("montant_total", 0)),
                    "doc_source": doc_id,
                })

            elif doc_type == "pret_immobilier":
                profile.setdefault("charges_deductibles", {}).setdefault("autres", []).append({
                    "type": "interets_emprunt",
                    "bien": entite.get("nom", "Bien immobilier"),
                    "capital_restant": montants.get("capital_restant_du", 0),
                    "interets_annuels": montants.get("interets_annuels", montants.get("interets", 0)),
                    "taux": montants.get("taux", 0),
                    "doc_source": doc_id,
                })

            elif doc_type in ("avis_imposition", "declaration_2042"):
                if montants.get("nb_parts"):
                    profile.setdefault("foyer", {})["nb_parts"] = montants["nb_parts"]
                if montants.get("revenu_fiscal_reference"):
                    profile.setdefault("notes", []).append(
                        f"RFR N-1 : {montants['revenu_fiscal_reference']} EUR (source: {doc_id})"
                    )

            elif doc_type in ("releve_titres", "ifu_titres"):
                cm = profile.setdefault("revenus", {}).setdefault("capitaux_mobiliers", {})
                cm["dividendes"] = cm.get("dividendes", 0) + montants.get("dividendes", 0)
                cm["interets"] = cm.get("interets", 0) + montants.get("interets", 0)
                cm["pfu_deja_preleve"] = cm.get("pfu_deja_preleve", 0) + montants.get("pfu_preleve", 0)
                cm.setdefault("sources", []).append({
                    "type": "ifu", "source": entite.get("nom", "Courtier"),
                    "montant": montants.get("dividendes", 0) + montants.get("interets", 0),
                })

            elif doc_type in ("scpi_ifu", "scpi_releve"):
                profile.setdefault("revenus", {}).setdefault("societe", []).append({
                    "type": "SCPI", "nom": entite.get("nom", "SCPI"), "regime_fiscal": "IR",
                    "revenus_fonciers_quote_part": montants.get("revenus_fonciers", 0),
                    "revenus_financiers": montants.get("revenus_financiers", 0),
                    "doc_source": doc_id,
                })

            elif doc_type in ("sci_bilan", "sci_releve"):
                profile.setdefault("revenus", {}).setdefault("societe", []).append({
                    "type": "SCI", "nom": entite.get("nom", "SCI"),
                    "regime_fiscal": montants.get("regime_fiscal", "IR"),
                    "revenus_fonciers_quote_part": montants.get("resultat_foncier", 0),
                    "dividendes": montants.get("dividendes", 0), "doc_source": doc_id,
                })

            elif doc_type in ("bail", "quittance_loyer"):
                profile.setdefault("revenus", {}).setdefault("foncier_nu", []).append({
                    "bien": entite.get("nom", montants.get("adresse", "Bien loue")),
                    "loyers_bruts": montants.get("loyer_annuel", montants.get("loyer_mensuel", 0) * 12),
                    "doc_source": doc_id,
                })

            for m in ext.get("donnees_manquantes", []):
                note = f"[{doc_id}] Donnee manquante : {m}"
                if note not in profile.get("notes", []):
                    profile.setdefault("notes", []).append(note)

        return profile

    def delete(self):
        if self.filepath.exists():
            self.filepath.unlink()
