"""
Profil Fiscal — Source de vérité unique du contribuable.

Ce profil JSON structuré se construit au fur et à mesure :
1. Les documents sont lus UNE SEULE FOIS pour alimenter le profil
2. Les questions complètent les trous
3. Le calcul fiscal utilise UNIQUEMENT ce profil (jamais les PDFs bruts)

Le profil est persisté sur disque et rechargé entre les sessions.
"""
import json
from copy import deepcopy
from datetime import datetime
from pathlib import Path

SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"


def _empty_profile() -> dict:
    """Retourne un profil fiscal vide avec la structure complète."""
    return {
        "meta": {
            "annee_revenus": 2025,
            "annee_declaration": 2026,
            "created_at": datetime.now().isoformat(),
            "updated_at": "",
            "completude": 0.0,  # 0.0 à 1.0
        },
        "foyer": {
            "situation": "",         # célibataire, marié, pacsé, divorcé, veuf
            "nb_parts": 0.0,
            "detail_parts": "",
            "parent_isole": False,   # case T
            "nb_enfants_mineurs": 0,
            "nb_enfants_majeurs_rattaches": 0,
            "nb_enfants_residence_alternee": 0,
            "nb_enfants_handicapes": 0,
            "invalidite_declarant1": False,  # case P
            "invalidite_declarant2": False,  # case F
        },
        "revenus": {
            "salaires": [],
            # [{"declarant": 1, "source": "ACME SA", "net_imposable": 48000,
            #   "pas_retenu": 4200, "heures_sup_exo": 0, "doc_source": "fiche_paie_dec.pdf"}]

            "pensions_retraite": [],
            # [{"declarant": 1, "source": "CNAV", "montant": 18000, "doc_source": "..."}]

            "foncier_nu": [],
            # [{"bien": "Paris 11e", "adresse": "...", "regime": "micro" ou "reel",
            #   "loyers_bruts": 12000, "charges_deductibles": 3200, "result_net": 8400,
            #   "doc_source": "..."}]

            "foncier_meuble": [],
            # [{"bien": "...", "type": "lmnp_classique" / "lmnp_saisonnier" / "lmp",
            #   "regime": "micro_bic" ou "reel", "recettes_brutes": 8000,
            #   "doc_source": "..."}]

            "capitaux_mobiliers": {
                "dividendes": 0,
                "interets": 0,
                "option_bareme": False,  # case 2OP
                "pfu_deja_preleve": 0,   # case 2CK
                "credits_impot_etranger": 0,  # case 2AB
                "sources": [],
                # [{"type": "dividendes", "source": "Boursorama", "montant": 5000}]
            },

            "plus_values": {
                "mobilières": 0,       # case 3VG
                "moins_values": 0,     # case 3VH
                "crypto": 0,          # case 3VT
                "sources": [],
            },

            "rsu_stock_options": [],
            # [{"type": "rsu" / "stock_option" / "bspce", "employeur": "...",
            #   "gain_acquisition": 50000, "date_acquisition": "2025-03-15",
            #   "gain_cession": 10000, "doc_source": "..."}]

            "societe": [],
            # [{"type": "SASU" / "SARL" / "SCI" / "SCPI" / "EURL",
            #   "nom": "Ma SCI", "regime_fiscal": "IR" ou "IS",
            #   "remuneration_gerant": 30000, "dividendes": 15000,
            #   "revenus_fonciers_quote_part": 0,
            #   "doc_source": "..."}]

            "micro_entrepreneur": {
                "bic_ventes": 0,
                "bic_services": 0,
                "bnc": 0,
                "sources": [],
            },

            "pensions_alimentaires_recues": [],
        },
        "charges_deductibles": {
            "pension_alimentaire_versee_enfants": 0,  # case 6GU
            "pension_alimentaire_versee_ascendants": 0,  # case 6GI
            "per_versements": 0,      # case 6NS
            "csg_deductible": 0,      # case 6DE
            "autres": [],
        },
        "reductions_credits": {
            "dons_interet_general": 0,     # case 7UF (66%)
            "dons_aide_personnes": 0,      # case 7UD (75%)
            "emploi_domicile": 0,          # case 7DB
            "garde_enfants": [],           # cases 7GA, 7GB, 7GC
            "frais_scolarite": {
                "college": 0,
                "lycee": 0,
                "superieur": 0,
            },
            "ehpad": 0,                   # case 7CD
            "investissement_locatif": {
                "dispositif": "",          # Pinel, Denormandie, etc.
                "montant": 0,
            },
            "autres": [],
        },
        "ifi": {
            "assujetti": False,
            "patrimoine_brut": 0,
            "dettes_deductibles": 0,
            "patrimoine_net": 0,
        },
        "documents_sources": [],
        # [{"filename": "fiche_paie_dec.pdf", "type": "bulletin_paie", "annee": 2025,
        #   "processed": True, "key_extractions": "Net imposable: 48000€"}]

        "donnees_manquantes": [],
        # ["situation familiale", "nombre d'enfants", "régime foncier"]

        "notes": [],
        # ["Le contribuable mentionne un bien en SCI non documenté"]
    }


class FiscalProfile:
    """Profil fiscal structuré — source de vérité unique."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.filepath = SESSIONS_DIR / f"{session_id}_profile.json"
        self.data = _empty_profile()
        self._load()

    def _load(self):
        if self.filepath.exists():
            try:
                self.data = json.loads(self.filepath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self.data = _empty_profile()

    def save(self):
        self.data["meta"]["updated_at"] = datetime.now().isoformat()
        self.data["meta"]["completude"] = self._compute_completeness()
        self.filepath.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )

    def is_new(self) -> bool:
        return not self.filepath.exists()

    # ------------------------------------------------------------------
    # Mise à jour du profil
    # ------------------------------------------------------------------

    def merge_extraction(self, extraction: dict, doc_filename: str):
        """Fusionne les données extraites d'un document dans le profil.

        L'extraction est un dict partiel qui peut contenir n'importe quelle
        clé du profil. Les listes sont appendées, les scalaires sont écrasés
        seulement si la valeur existante est vide/zéro.
        """
        self._deep_merge(self.data, extraction)

        # Enregistrer le document comme traité
        already = [d["filename"] for d in self.data.get("documents_sources", [])]
        if doc_filename not in already:
            self.data.setdefault("documents_sources", []).append({
                "filename": doc_filename,
                "processed": True,
                "processed_at": datetime.now().isoformat(),
            })

        self.save()

    def merge_user_answers(self, answers: dict):
        """Fusionne les réponses utilisateur dans le profil."""
        self._deep_merge(self.data, answers)
        self.save()

    def set_missing_fields(self, fields: list[str]):
        """Met à jour la liste des données manquantes."""
        self.data["donnees_manquantes"] = fields
        self.save()

    def add_note(self, note: str):
        self.data.setdefault("notes", []).append(note)
        self.save()

    # ------------------------------------------------------------------
    # Accès au profil
    # ------------------------------------------------------------------

    def get_for_llm(self) -> str:
        """Retourne le profil formaté pour injection dans un prompt LLM.
        C'est la SEULE chose que le LLM voit — jamais les PDFs bruts."""
        # Copie nettoyée (sans meta, sans docs_sources détaillés)
        clean = deepcopy(self.data)
        clean.pop("meta", None)

        # Simplifier documents_sources pour le LLM
        docs = clean.pop("documents_sources", [])
        clean["documents_traites"] = [d["filename"] for d in docs]

        # Enlever les listes/dicts vides
        clean = self._prune_empty(clean)

        return json.dumps(clean, indent=2, ensure_ascii=False)

    def get_missing_summary(self) -> str:
        """Retourne un résumé des données manquantes."""
        missing = self.data.get("donnees_manquantes", [])
        if not missing:
            return "Profil complet — aucune donnée manquante."
        return "Données manquantes :\n" + "\n".join(f"- {m}" for m in missing)

    def get_completeness(self) -> float:
        return self.data.get("meta", {}).get("completude", 0.0)

    def get_raw(self) -> dict:
        return deepcopy(self.data)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _deep_merge(self, target: dict, source: dict):
        """Fusionne source dans target récursivement.
        - Listes : append les éléments qui n'existent pas déjà
        - Dicts : merge récursif
        - Scalaires : écrase seulement si target est vide/zéro/False
        """
        for key, value in source.items():
            if key not in target:
                target[key] = deepcopy(value)
            elif isinstance(value, dict) and isinstance(target[key], dict):
                self._deep_merge(target[key], value)
            elif isinstance(value, list) and isinstance(target[key], list):
                for item in value:
                    if item not in target[key]:
                        target[key].append(deepcopy(item))
            elif isinstance(value, (int, float)):
                # Écraser seulement si la valeur actuelle est 0
                if target[key] == 0 or target[key] == 0.0:
                    target[key] = value
                elif value != 0:
                    # Si les deux sont non-zéro et différents, prendre la nouvelle
                    target[key] = value
            elif isinstance(value, str) and value:
                if not target[key]:
                    target[key] = value
                else:
                    target[key] = value  # Nouvelle info écrase
            elif isinstance(value, bool):
                if value:  # True écrase toujours
                    target[key] = value

    def _prune_empty(self, d: dict) -> dict:
        """Supprime les valeurs vides/zéro pour alléger le contexte LLM."""
        result = {}
        for k, v in d.items():
            if isinstance(v, dict):
                pruned = self._prune_empty(v)
                if pruned:
                    result[k] = pruned
            elif isinstance(v, list):
                if v:  # Garder seulement les listes non vides
                    result[k] = v
            elif isinstance(v, str):
                if v:
                    result[k] = v
            elif isinstance(v, bool):
                if v:
                    result[k] = v
            elif isinstance(v, (int, float)):
                if v != 0:
                    result[k] = v
        return result

    def _compute_completeness(self) -> float:
        """Estime le taux de complétude du profil (0.0 à 1.0)."""
        checks = [
            bool(self.data["foyer"]["situation"]),
            self.data["foyer"]["nb_parts"] > 0,
            bool(self.data["revenus"]["salaires"]) or bool(self.data["revenus"]["pensions_retraite"]),
            len(self.data.get("documents_sources", [])) > 0,
            len(self.data.get("donnees_manquantes", [])) == 0,
        ]
        return sum(checks) / len(checks)

    def delete(self):
        if self.filepath.exists():
            self.filepath.unlink()
