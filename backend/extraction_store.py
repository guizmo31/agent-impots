"""
Store des extractions structurées — RAG local sur les données du contribuable.

Pipeline :
  Document brut -> Extraction structurée universelle -> Indexé dans un RAG local

L'extraction suit un format UNIQUE quel que soit le document :
  {
    "doc_id": "fiche_paie_dec_2025.pdf",
    "type_document": "fiche_de_paie",
    "periode": {"debut": "2025-01-01", "fin": "2025-12-31"},
    "entite": {"nom": "ACME SA", "siren": "123456789", "role": "employeur"},
    "montants": {
      "salaire_brut": 52000,
      "net_imposable": 42000,
      "pas_retenu": 3800
    },
    "donnees_manquantes": ["heures supplémentaires exonérées non visibles"],
    "confiance": 0.9,
    "resume": "Bulletin de paie décembre 2025, cumul annuel net imposable 42 000€"
  }

Ce store permet ensuite de :
1. Chercher par type ("tous les bulletins de paie")
2. Chercher par entité ("tout ce qui concerne la SCI Dupont")
3. Chercher par montant ("revenus fonciers")
4. Alimenter automatiquement le FiscalProfile
"""
import json
import math
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx

SESSIONS_DIR = Path(__file__).resolve().parent.parent / "sessions"
OLLAMA_URL = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


class ExtractionStore:
    """Store persistant + RAG local des extractions structurées."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.filepath = SESSIONS_DIR / f"{session_id}_extractions.json"
        self.extractions: list[dict] = []
        self.embeddings: list[list[float]] = []
        self._load()

    def _load(self):
        if self.filepath.exists():
            try:
                data = json.loads(self.filepath.read_text(encoding="utf-8"))
                self.extractions = data.get("extractions", [])
                self.embeddings = data.get("embeddings", [])
            except (json.JSONDecodeError, OSError):
                self.extractions = []
                self.embeddings = []

    def save(self):
        data = {
            "session_id": self.session_id,
            "updated_at": datetime.now().isoformat(),
            "count": len(self.extractions),
            "extractions": self.extractions,
            "embeddings": self.embeddings,
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
        """Ajoute une extraction structuree et sauvegarde sur disque immediatement.

        L'embedding n'est PAS genere ici (trop lent). Il sera genere en batch
        par finalize_embeddings() une fois l'ingestion terminee.
        Mais le JSON est sauvegarde a chaque document pour survivre a un crash.
        """
        doc_id = extraction.get("doc_id", "")
        # Retirer le doublon eventuel + son embedding
        new_extractions = []
        new_embeddings = []
        for j, e in enumerate(self.extractions):
            if e.get("doc_id") != doc_id:
                new_extractions.append(e)
                if j < len(self.embeddings):
                    new_embeddings.append(self.embeddings[j])
        self.extractions = new_extractions
        self.embeddings = new_embeddings

        # Ajouter la nouvelle extraction
        extraction["_index_text"] = self._extraction_to_text(extraction)
        self.extractions.append(extraction)
        self.embeddings.append([])  # Placeholder, sera rempli par finalize

        # Sauvegarder sur disque immediatement (survit a un crash/kill)
        self.save()

    def finalize_embeddings(self):
        """Genere les embeddings manquants en une seule passe, puis sauvegarde.
        A appeler UNE SEULE FOIS apres l'ingestion de tous les documents."""
        generated = 0
        for i, ext in enumerate(self.extractions):
            if i >= len(self.embeddings) or not self.embeddings[i]:
                emb = self._get_embedding(ext.get("_index_text", ""))
                if i < len(self.embeddings):
                    self.embeddings[i] = emb
                else:
                    self.embeddings.append(emb)
                generated += 1
        print(f"[STORE] {generated} embeddings generes pour {len(self.extractions)} extractions")
        self.save()

    # ------------------------------------------------------------------
    # Recherche RAG dans les extractions
    # ------------------------------------------------------------------

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Recherche sémantique dans les extractions structurées."""
        if not self.extractions:
            return []

        query_emb = self._get_embedding(query)

        # Score hybride : embedding + mots-clés
        results = []
        query_tokens = set(re.findall(r"\w+", query.lower()))

        for i, ext in enumerate(self.extractions):
            # Score embedding
            emb_score = 0.0
            if query_emb and i < len(self.embeddings) and self.embeddings[i]:
                emb_score = _cosine_similarity(query_emb, self.embeddings[i])

            # Score mots-clés
            index_text = ext.get("_index_text", "").lower()
            text_tokens = set(re.findall(r"\w+", index_text))
            common = query_tokens & text_tokens
            keyword_score = len(common) / max(len(query_tokens), 1)

            # Hybride 60% embedding + 40% keywords
            score = 0.6 * emb_score + 0.4 * keyword_score if emb_score else keyword_score
            results.append((score, ext))

        results.sort(key=lambda x: x[0], reverse=True)
        return [ext for score, ext in results[:top_k] if score > 0.05]

    def search_by_type(self, doc_type: str) -> list[dict]:
        """Retourne toutes les extractions d'un type donné."""
        return [e for e in self.extractions if e.get("type_document", "").lower() == doc_type.lower()]

    def search_by_entity(self, entity_name: str) -> list[dict]:
        """Retourne les extractions liées à une entité."""
        name_lower = entity_name.lower()
        return [
            e for e in self.extractions
            if name_lower in e.get("entite", {}).get("nom", "").lower()
        ]

    def get_all(self) -> list[dict]:
        """Retourne toutes les extractions."""
        return self.extractions

    def get_all_for_llm(self) -> str:
        """Retourne toutes les extractions formatées pour un prompt LLM."""
        if not self.extractions:
            return "(Aucune extraction)"

        parts = []
        for ext in self.extractions:
            parts.append(self._extraction_to_text(ext))
        return "\n\n---\n\n".join(parts)

    def get_summary(self) -> dict:
        """Retourne un résumé des extractions pour l'UI."""
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
        """Retourne toutes les données manquantes détectées."""
        missing = []
        for ext in self.extractions:
            for m in ext.get("donnees_manquantes", []):
                if m not in missing:
                    missing.append(m)
        return missing

    # ------------------------------------------------------------------
    # Construction du profil fiscal depuis les extractions
    # ------------------------------------------------------------------

    def build_profile_data(self) -> dict:
        """Construit les données du profil fiscal à partir des extractions.
        Retourne un dict partiel compatible FiscalProfile.merge_extraction()."""
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
                        f"RFR N-1 : {montants['revenu_fiscal_reference']}€ (source: {doc_id})"
                    )

            elif doc_type in ("releve_titres", "ifu_titres"):
                cm = profile.setdefault("revenus", {}).setdefault("capitaux_mobiliers", {})
                cm["dividendes"] = cm.get("dividendes", 0) + montants.get("dividendes", 0)
                cm["interets"] = cm.get("interets", 0) + montants.get("interets", 0)
                cm["pfu_deja_preleve"] = cm.get("pfu_deja_preleve", 0) + montants.get("pfu_preleve", 0)
                cm.setdefault("sources", []).append({
                    "type": "ifu",
                    "source": entite.get("nom", "Courtier"),
                    "montant": montants.get("dividendes", 0) + montants.get("interets", 0),
                })

            elif doc_type in ("scpi_ifu", "scpi_releve"):
                profile.setdefault("revenus", {}).setdefault("societe", []).append({
                    "type": "SCPI",
                    "nom": entite.get("nom", "SCPI"),
                    "regime_fiscal": "IR",
                    "revenus_fonciers_quote_part": montants.get("revenus_fonciers", 0),
                    "revenus_financiers": montants.get("revenus_financiers", 0),
                    "doc_source": doc_id,
                })

            elif doc_type in ("sci_bilan", "sci_releve"):
                profile.setdefault("revenus", {}).setdefault("societe", []).append({
                    "type": "SCI",
                    "nom": entite.get("nom", "SCI"),
                    "regime_fiscal": montants.get("regime_fiscal", "IR"),
                    "revenus_fonciers_quote_part": montants.get("resultat_foncier", 0),
                    "dividendes": montants.get("dividendes", 0),
                    "doc_source": doc_id,
                })

            elif doc_type in ("bail", "quittance_loyer"):
                profile.setdefault("revenus", {}).setdefault("foncier_nu", []).append({
                    "bien": entite.get("nom", montants.get("adresse", "Bien loué")),
                    "loyers_bruts": montants.get("loyer_annuel", montants.get("loyer_mensuel", 0) * 12),
                    "doc_source": doc_id,
                })

            # Toujours ajouter les notes de données manquantes
            for m in ext.get("donnees_manquantes", []):
                note = f"[{doc_id}] Donnée manquante : {m}"
                if note not in profile.get("notes", []):
                    profile.setdefault("notes", []).append(note)

        return profile

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _extraction_to_text(self, ext: dict) -> str:
        """Convertit une extraction en texte indexable."""
        parts = []
        parts.append(f"Document: {ext.get('doc_id', '?')}")
        parts.append(f"Type: {ext.get('type_document', '?')}")

        periode = ext.get("periode", {})
        if periode:
            parts.append(f"Période: {periode.get('debut', '?')} à {periode.get('fin', '?')}")

        entite = ext.get("entite", {})
        if entite.get("nom"):
            role = entite.get("role", "")
            siren = f" (SIREN: {entite['siren']})" if entite.get("siren") else ""
            parts.append(f"Entité: {entite['nom']}{siren} [{role}]")

        montants = ext.get("montants", {})
        if montants:
            for key, val in montants.items():
                if isinstance(val, (int, float)) and val > 0:
                    parts.append(f"{key}: {val:,.2f}€")
                elif isinstance(val, str) and val:
                    parts.append(f"{key}: {val}")

        resume = ext.get("resume", "")
        if resume:
            parts.append(f"Résumé: {resume}")

        missing = ext.get("donnees_manquantes", [])
        if missing:
            parts.append(f"Manquant: {', '.join(missing)}")

        return "\n".join(parts)

    def _get_embedding(self, text: str) -> list[float]:
        """Génère un embedding via Ollama (synchrone pour simplicité)."""
        if not text:
            return []
        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    f"{OLLAMA_URL}/api/embeddings",
                    json={"model": EMBED_MODEL, "prompt": text[:2000]},
                )
                if response.status_code == 200:
                    return response.json().get("embedding", [])
        except Exception:
            pass
        return []

    def delete(self):
        if self.filepath.exists():
            self.filepath.unlink()
