"""
Base de connaissances fiscales -- injection directe dans les prompts.

Remplace le RAG (embeddings + TF-IDF) par un simple chargement des fichiers
data/ en memoire. La base fait ~100 Ko, ce qui tient largement dans la
fenetre de 128K tokens de Mistral-Nemo.

Plus rapide, plus fiable (le LLM voit TOUT), et plus simple.
"""
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

_cache: dict[str, str] = {}


def get_fiscal_rules() -> str:
    """Retourne les regles fiscales completes (markdown)."""
    if "rules" not in _cache:
        path = DATA_DIR / "regles_fiscales.md"
        _cache["rules"] = path.read_text(encoding="utf-8") if path.exists() else ""
    return _cache["rules"]


def get_cases_json() -> dict:
    """Retourne le JSON complet des cases 2042."""
    if "cases_raw" not in _cache:
        path = DATA_DIR / "cases_2042_2026.json"
        if path.exists():
            _cache["cases_raw"] = json.loads(path.read_text(encoding="utf-8"))
        else:
            _cache["cases_raw"] = {}
    return _cache["cases_raw"]


def get_cases_summary() -> str:
    """Retourne un resume compact des cases (pour injection dans un prompt)."""
    if "cases_summary" in _cache:
        return _cache["cases_summary"]

    data = get_cases_json()
    parts = []

    # Bareme
    bareme = data.get("bareme_ir", {})
    if bareme:
        parts.append("## Bareme IR")
        for t in bareme.get("tranches", []):
            max_val = f"{t['max']:,.0f}" if t["max"] else "+"
            parts.append(f"  {t['min']:,.0f} - {max_val} EUR : {t['taux']*100:.0f}%")
        abat = bareme.get("abattement_10pct", {})
        if abat:
            parts.append(f"  Abattement 10% : min {abat.get('minimum')} EUR, max {abat.get('maximum')} EUR")
        decote = bareme.get("decote", {})
        if decote:
            parts.append(f"  Decote : celibataire {decote.get('seuil_celibataire')} EUR, couple {decote.get('seuil_couple')} EUR")

    # Cases par categorie
    cases = data.get("cases", {})
    for cat_id, case_dict in cases.items():
        cat_label = cat_id.replace("_", " ").title()
        case_lines = []
        for case_id, info in case_dict.items():
            if not isinstance(info, dict):
                continue
            libelle = info.get("libelle", "")
            desc = info.get("description", "")
            line = f"  {case_id} : {libelle}"
            if desc and desc != libelle:
                line += f" -- {desc[:150]}"
            extras = []
            if info.get("abattement"):
                v = info["abattement"]
                extras.append(f"abat:{v*100:.0f}%" if isinstance(v, float) and v < 1 else f"abat:{v}")
            if info.get("taux_reduction"):
                extras.append(f"reduction:{info['taux_reduction']*100:.0f}%")
            if info.get("taux_credit"):
                extras.append(f"credit:{info['taux_credit']*100:.0f}%")
            if info.get("plafond_base"):
                extras.append(f"plafond:{info['plafond_base']} EUR")
            if info.get("seuil"):
                extras.append(f"seuil:{info['seuil']} EUR")
            if info.get("article_cgi"):
                extras.append(info["article_cgi"])
            if extras:
                line += f" [{', '.join(extras)}]"
            case_lines.append(line)

        if case_lines:
            parts.append(f"\n## {cat_label}")
            parts.extend(case_lines)

    # Parts fiscales
    pf = data.get("regles_parts_fiscales", {})
    if pf:
        parts.append("\n## Parts fiscales")
        base = pf.get("base", {})
        for sit, val in base.items():
            parts.append(f"  {sit.replace('_', ' ')} : {val} part(s)")
        enfants = pf.get("enfants_a_charge", {})
        parts.append(f"  1er enfant: +{enfants.get('1er_enfant', 0.5)}, 2eme: +{enfants.get('2eme_enfant', 0.5)}, 3eme+: +{enfants.get('a_partir_3eme', 1.0)}")

    result = "\n".join(parts)
    _cache["cases_summary"] = result
    return result


def get_full_context_for_llm() -> str:
    """Retourne le contexte fiscal COMPLET a injecter dans le prompt.
    Contient les cases + les regles. ~100 Ko = ~25K tokens."""
    if "full" in _cache:
        return _cache["full"]

    result = "# REFERENTIEL FISCAL OFFICIEL\n\n"
    result += get_cases_summary()
    result += "\n\n# REGLES FISCALES DETAILLEES\n\n"
    result += get_fiscal_rules()

    _cache["full"] = result
    print(f"[FISCAL] Base de connaissances chargee : {len(result):,} chars")
    return result


def get_all_case_ids() -> set[str]:
    """Retourne l'ensemble des numeros de cases connus."""
    if "case_ids" in _cache:
        return _cache["case_ids"]
    data = get_cases_json()
    ids = set()
    for cat_dict in data.get("cases", {}).values():
        for case_id, info in cat_dict.items():
            if isinstance(info, dict):
                ids.add(case_id)
                if info.get("case"):
                    ids.add(info["case"])
    _cache["case_ids"] = ids
    return ids


def clear_cache():
    """Vide le cache (utile apres modification des fichiers data/)."""
    _cache.clear()
