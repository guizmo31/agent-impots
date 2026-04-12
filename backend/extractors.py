"""
Extracteur universel de données fiscales structurées.

Chaque document passe par le MÊME prompt, qui produit une extraction
avec un format UNIQUE :

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

Un seul prompt. Un seul format. Fini les extracteurs ad-hoc.
"""
import json
import re
from ollama_client import query_llm
from sanitizer import sanitize_document_content


EXTRACTION_SYSTEM = (
    "Tu es un extracteur de données fiscales. "
    "Tu analyses un document et tu produis une extraction structurée au format JSON. "
    "Tu ne devines JAMAIS un montant — si tu ne le trouves pas, mets null. "
    "Tu signales toujours les données manquantes ou ambiguës. "
    "Réponds UNIQUEMENT en JSON valide."
)

EXTRACTION_PROMPT_TEMPLATE = """## Document à analyser

Nom du fichier : {filename}

### Contenu du document :
{content}

## Instructions

Extrais de ce document TOUTES les informations fiscales structurées.

### Format de sortie (JSON strict) :

```json
{{
  "doc_id": "{filename}",
  "type_document": "TYPE",
  "periode": {{"debut": "AAAA-MM-JJ", "fin": "AAAA-MM-JJ"}},
  "entite": {{"nom": "Nom de l'entité", "siren": "SIREN si visible", "role": "ROLE"}},
  "montants": {{
    "cle_montant": valeur_numerique
  }},
  "donnees_manquantes": ["info manquante 1", "info manquante 2"],
  "confiance": 0.9,
  "resume": "Résumé en 1 ligne"
}}
```

### Types de documents possibles :
fiche_de_paie, avis_imposition, declaration_2042, taxe_fonciere, pret_immobilier,
releve_bancaire, releve_titres, ifu_titres, scpi_ifu, scpi_releve,
sci_bilan, sci_releve, dividendes_ifu, bail, quittance_loyer,
facture, attestation_employeur, releve_assurance_vie, avis_cfe,
micro_entrepreneur_ca, autre

### Rôles d'entité possibles :
employeur, banque, assureur, notaire, bailleur, locataire, sci, scpi,
administration_fiscale, courtier, societe_gestion, autre

### Clés de montants courantes (utilise celles qui s'appliquent) :
- Paie : salaire_brut, salaire_net, net_imposable, pas_retenu, heures_sup_exonerees, cumul_conges
- Foncier : loyer_mensuel, loyer_annuel, charges_copro, taxe_fonciere, taxe_ordures_menageres
- Prêt : capital_emprunte, capital_restant_du, interets_annuels, assurance_annuelle, taux, duree_mois
- Titres : dividendes, interets, plus_values, moins_values, pfu_preleve, credits_impot_etranger
- SCPI : revenus_fonciers, revenus_financiers, credits_impot_etranger, valeur_parts
- SCI : resultat_foncier, loyers_encaisses, charges_deductibles, interets_emprunt
- Société : remuneration_gerant, dividendes, benefice_net, capital_social, regime_fiscal
- Impôts : revenu_fiscal_reference, nb_parts, impot_du, montant_preleve, solde
- Micro-entrepreneur : chiffre_affaires, type_activite

### Règles :
1. Si le document contient des CUMULS ANNUELS, privilégie-les aux montants mensuels
2. Si un montant est ambigu (ex: plusieurs "net imposable"), prends le CUMUL ANNUEL
3. Mets null (pas 0) pour les montants non trouvés
4. Le champ "confiance" va de 0.0 (illisible) à 1.0 (parfaitement clair)
5. Liste dans "donnees_manquantes" tout ce qui serait utile mais n'est pas dans le document"""


async def extract_structured(filename: str, content: str) -> dict | None:
    """Extrait les données fiscales structurées d'un document.

    Returns:
        Un dict au format universel, ou None si l'extraction échoue.
    """
    # Sanitizer anti-prompt-injection AVANT envoi au LLM
    content, security_warnings = sanitize_document_content(content, filename)
    for w in security_warnings:
        print(w)

    # Adapter la taille du contenu envoye
    if len(content) > 6000:
        head = content[:3500]
        tail = content[-2000:]
        content_for_llm = f"{head}\n\n[... milieu du document omis ...]\n\n{tail}"
    else:
        content_for_llm = content

    prompt = EXTRACTION_PROMPT_TEMPLATE.format(
        filename=filename,
        content=content_for_llm,
    )

    response = await query_llm(
        prompt, EXTRACTION_SYSTEM,
        temperature=0.1, max_tokens=1500,
    )

    result = _parse_json(response)

    if result:
        # S'assurer que doc_id est bien le nom du fichier
        result["doc_id"] = filename
        # Nettoyer les montants null
        montants = result.get("montants", {})
        result["montants"] = {k: v for k, v in montants.items() if v is not None}
        print(f"[EXTRACT] {filename} -> {result.get('type_document', '?')} | "
              f"{len(result.get('montants', {}))} montants | "
              f"confiance: {result.get('confiance', '?')}")
    else:
        print(f"[EXTRACT] ÉCHEC pour {filename}")

    return result


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
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    c = json.loads(text[start:i + 1])
                    if best is None or len(text[start:i + 1]) > len(json.dumps(best)):
                        best = c
                except json.JSONDecodeError:
                    pass
                start = -1
    return best
