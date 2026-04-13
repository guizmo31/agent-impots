"""
Page de reference fiscale — guide des cases 2042 et regles fiscales.

Genere une page HTML interactive a partir de :
- data/cases_2042_2026.json (toutes les cases)
- data/regles_fiscales.md (regles detaillees)

Inclut une barre de recherche instantanee (filtrage cote client).
"""
import json
import re
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Exemples concrets pour les cases les plus courantes
EXEMPLES = {
    "1AJ": "Vous etes salarie chez Renault avec un salaire net imposable annuel de 42 000 EUR (visible sur votre bulletin de paie de decembre, ligne 'Cumul net imposable'). Inscrivez 42 000 en case 1AJ.",
    "1BJ": "Votre conjoint(e) travaille chez Airbus avec un net imposable de 38 000 EUR/an. Inscrivez 38 000 en case 1BJ.",
    "1AK": "Vous avez fait 200h supplementaires dans l'annee, exonerees a hauteur de 5 000 EUR. Inscrivez 5 000 en case 1AK. Ce montant n'est pas ajoute au revenu imposable.",
    "1GB": "Vous etes gerant majoritaire de votre SARL et vous versez 36 000 EUR/an de remuneration. Inscrivez 36 000 en case 1GB (pas en 1AJ car article 62 du CGI).",
    "1AS": "Vous percevez une retraite CNAV de 1 500 EUR/mois soit 18 000 EUR/an. Inscrivez 18 000 en case 1AS. Un abattement de 10% sera applique automatiquement (min 422 EUR, max 4 123 EUR).",
    "1TZ": "Vous avez recu 200 actions gratuites (RSU) de votre employeur americain. Valeur a l'acquisition : 50 EUR/action, soit un gain de 10 000 EUR. Comme c'est < 300 000 EUR, inscrivez 10 000 en case 1TZ (abattement de 50% applique, soit 5 000 EUR imposable).",
    "1TT": "Vous avez leve vos stock-options : prix d'exercice 20 EUR, valeur a la levee 45 EUR, 500 actions. Gain de levee = (45-20) x 500 = 12 500 EUR. Inscrivez 12 500 en case 1TT.",
    "2DC": "Votre SASU vous a verse 8 000 EUR de dividendes. Inscrivez 8 000 en case 2DC. Par defaut, le PFU de 30% s'applique (2 400 EUR d'impot). Si vous cochez 2OP, l'abattement de 40% s'applique et seuls 4 800 EUR sont ajoutes a vos revenus.",
    "2TR": "Votre livret bancaire imposable vous a rapporte 350 EUR d'interets. Inscrivez 350 en case 2TR.",
    "2OP": "Vous avez des dividendes de 8 000 EUR et une TMI de 11%. Cochez 2OP : avec l'abattement de 40%, seuls 4 800 EUR sont imposes a 11% = 528 EUR (au lieu de 1 024 EUR au PFU). Economie : 496 EUR.",
    "2CK": "Votre banque a deja preleve un acompte de 12,8% sur vos 350 EUR d'interets = 44,80 EUR. Inscrivez 44,80 en case 2CK. Ce montant sera deduit de votre impot final.",
    "3VG": "Vous avez vendu des actions pour 15 000 EUR achetees 10 000 EUR. Plus-value = 5 000 EUR. Inscrivez 5 000 en case 3VG. PFU 30% = 1 500 EUR d'impot (ou option bareme si plus avantageux).",
    "3VH": "Vous avez vendu des actions a perte : achetees 8 000 EUR, vendues 5 000 EUR. Moins-value = 3 000 EUR. Inscrivez 3 000 en case 3VH. Reportable 10 ans sur vos futures plus-values.",
    "3VT": "Vous avez vendu du Bitcoin pour 2 000 EUR de plus-value (total cessions > 305 EUR dans l'annee). Inscrivez 2 000 en case 3VT. PFU 30% = 600 EUR.",
    "4BA": "Vous louez un appartement nu a Toulouse : 800 EUR/mois de loyer. Charges deductibles : interets emprunt 2 400 EUR + taxe fonciere 1 200 EUR + assurance 300 EUR + travaux 1 500 EUR = 5 400 EUR. Revenu foncier net = 9 600 - 5 400 = 4 200 EUR. Inscrivez 4 200 en case 4BA.",
    "4BE": "Vous louez un studio nu : 600 EUR/mois soit 7 200 EUR/an de loyers bruts (< 15 000 EUR). Inscrivez 7 200 en case 4BE. L'abattement de 30% est automatique, vous serez impose sur 5 040 EUR.",
    "4BF": "Vos charges deductibles (12 000 EUR) depassent vos loyers (9 600 EUR) : deficit foncier de 2 400 EUR. Inscrivez 2 400 en case 4BF. Ce montant se deduit de votre revenu global (plafond 10 700 EUR).",
    "5ND": "Vous louez un appartement meuble a l'annee : 900 EUR/mois soit 10 800 EUR de recettes. Inscrivez 10 800 en case 5ND (micro-BIC, abattement 50% automatique, impose sur 5 400 EUR).",
    "5NG": "Vous louez un gite classe 'meuble de tourisme' : 15 000 EUR de recettes. Inscrivez 15 000 en case 5NG (micro-BIC, abattement 71%, impose sur seulement 4 350 EUR).",
    "5NJ": "Vous louez votre appartement sur Airbnb (non classe) : 8 000 EUR de recettes. Inscrivez 8 000 en case 5NJ (micro-BIC, abattement 50%, impose sur 4 000 EUR).",
    "5KO": "Vous etes auto-entrepreneur en vente de marchandises : CA de 45 000 EUR. Inscrivez 45 000 en case 5KO. Abattement 71% automatique, impose sur 13 050 EUR.",
    "5KP": "Vous etes auto-entrepreneur en prestation de services : CA de 30 000 EUR. Inscrivez 30 000 en case 5KP. Abattement 50%, impose sur 15 000 EUR.",
    "5HQ": "Vous exercez en liberal (BNC) en micro : 25 000 EUR de recettes. Inscrivez 25 000 en case 5HQ. Abattement 34%, impose sur 16 500 EUR.",
    "6GU": "Votre fils majeur (22 ans, non rattache) est etudiant. Vous lui versez 500 EUR/mois = 6 000 EUR/an. Inscrivez 6 000 en case 6GU (plafond 6 674 EUR). Votre fils doit declarer 6 000 EUR de son cote.",
    "6GI": "Votre mere agee vit chez vous. Vous la nourrissez et l'hebergez : deduction forfaitaire de 3 968 EUR (sans justificatif). Vous payez aussi ses frais medicaux : 1 500 EUR. Inscrivez 5 468 EUR en case 6GI.",
    "6NS": "Vous avez verse 4 000 EUR sur votre PER (Plan Epargne Retraite). Inscrivez 4 000 en case 6NS. Ce montant se deduit de votre revenu imposable. Si votre TMI est 30%, economie d'impot = 1 200 EUR.",
    "7UF": "Vous avez donne 500 EUR a une association d'interet general (Restos du Coeur, Croix-Rouge...). Inscrivez 500 en case 7UF. Reduction d'impot = 66% x 500 = 330 EUR.",
    "7UD": "Vous avez donne 200 EUR a une association d'aide aux personnes en difficulte. Inscrivez 200 en case 7UD. Reduction = 75% x 200 = 150 EUR (plafond 1 000 EUR pour le taux de 75%).",
    "7DB": "Vous employez une femme de menage 4h/semaine a 15 EUR/h = 3 120 EUR/an. Inscrivez 3 120 en case 7DB. Credit d'impot = 50% x 3 120 = 1 560 EUR (plafond 12 000 EUR).",
    "7GA": "Vous payez la creche pour votre enfant de 3 ans : 3 000 EUR/an (apres deduction du complement CAF). Inscrivez 3 000 en case 7GA. Credit d'impot = 50% x 3 000 = 1 500 EUR (plafond 3 500 EUR).",
    "7EA": "Votre enfant est au college. Inscrivez 1 en case 7EA. Reduction = 61 EUR.",
    "7EC": "Votre enfant est au lycee. Inscrivez 1 en case 7EC. Reduction = 153 EUR.",
    "7EF": "Votre enfant est etudiant a l'universite. Inscrivez 1 en case 7EF. Reduction = 183 EUR.",
    "7CD": "Votre parent est en EHPAD : 2 500 EUR/mois dont 1 800 EUR d'hebergement et dependance (hors soins). Sur l'annee : 21 600 EUR. Inscrivez 10 000 EUR en case 7CD (plafond). Reduction = 25% x 10 000 = 2 500 EUR.",
    "8HV": "Votre employeur a retenu 4 200 EUR de prelevement a la source durant l'annee (visible sur chaque bulletin de paie). Ce montant est pre-rempli en case 8HV et sera deduit de votre impot final.",
    "0CF": "Vous avez 2 enfants mineurs. Inscrivez 2 en case 0CF. Cela vous donne +0,5 part (1er enfant) +0,5 part (2eme enfant) = +1 part supplementaire.",
    "T": "Vous etes divorc(e) et vivez seul(e) avec vos 2 enfants. Cochez la case T. Au lieu de 1 + 0,5 + 0,5 = 2 parts, vous aurez 1 + 1 + 0,5 = 2,5 parts (le 1er enfant compte pour 1 part entiere).",
    "L": "Vous avez 60 ans, vous vivez seul(e) et vous avez eleve votre fils pendant 15 ans (il est maintenant adulte independant). Cochez la case L. Vous beneficiez d'une demi-part supplementaire (avantage plafonne a 1 050 EUR).",
    "P": "Vous etes titulaire de la carte mobilite inclusion (CMI) mention invalidite (taux >= 80%). Cochez la case P pour beneficier d'une demi-part supplementaire.",
    "2TS": "Votre SCPI Corum vous a distribue 1 200 EUR de revenus financiers (indiques sur l'IFU). Inscrivez 1 200 en case 2TS.",
    "9HI": "Vous possedez votre residence principale (estimee 400 000 EUR, abattement 30% = 280 000 EUR), un appartement locatif (250 000 EUR) et des parts de SCPI (80 000 EUR). Total brut = 610 000 EUR. Dettes : pret restant 180 000 EUR. Net = 430 000 EUR. C'est < 1 300 000 EUR, vous n'etes pas assujetti a l'IFI.",
}

# Exemples de calcul pour le bareme
EXEMPLES_BAREME = [
    {
        "titre": "Celibataire, 30 000 EUR de salaire",
        "etapes": [
            "Salaire net imposable : 30 000 EUR",
            "Abattement 10% : 3 000 EUR",
            "Revenu net imposable : 27 000 EUR",
            "1 part fiscale (celibataire sans enfant)",
            "Quotient familial : 27 000 / 1 = 27 000 EUR",
            "Tranche 0% : 11 497 x 0% = 0 EUR",
            "Tranche 11% : (27 000 - 11 497) x 11% = 1 705 EUR",
            "Impot brut = 1 705 EUR",
        ],
    },
    {
        "titre": "Couple marie, 2 enfants, 60 000 EUR de salaires",
        "etapes": [
            "Salaires : declarant 1 = 35 000 EUR, declarant 2 = 25 000 EUR",
            "Total brut : 60 000 EUR",
            "Abattement 10% : 6 000 EUR",
            "Revenu net imposable : 54 000 EUR",
            "3 parts fiscales (2 adultes + 0,5 + 0,5 enfants)",
            "Quotient familial : 54 000 / 3 = 18 000 EUR",
            "Tranche 0% : 11 497 x 0% = 0 EUR",
            "Tranche 11% : (18 000 - 11 497) x 11% = 715 EUR",
            "Impot par part = 715 EUR",
            "Impot brut = 715 x 3 = 2 146 EUR",
            "PAS deja paye : 5 000 EUR -> Remboursement de 2 854 EUR",
        ],
    },
    {
        "titre": "Celibataire avec appartement Airbnb",
        "etapes": [
            "Salaire net imposable : 40 000 EUR (case 1AJ)",
            "Location Airbnb non classee : 8 000 EUR (case 5NJ, micro-BIC abattement 50%)",
            "Revenu Airbnb apres abattement : 4 000 EUR",
            "Total revenus : 40 000 + 4 000 = 44 000 EUR",
            "Abattement 10% sur salaires : 4 000 EUR",
            "Revenu net imposable : 40 000 EUR",
            "QF : 40 000 / 1 = 40 000 EUR",
            "Impot brut : 0 + 1 960 + (40 000 - 29 315) x 30% = 1 960 + 3 206 = 5 166 EUR",
        ],
    },
]


def generate_reference_html() -> str:
    """Genere la page HTML de reference fiscale."""
    # Charger les cases
    cases_path = DATA_DIR / "cases_2042_2026.json"
    cases_data = {}
    if cases_path.exists():
        cases_data = json.loads(cases_path.read_text(encoding="utf-8"))

    # Charger les regles
    regles_path = DATA_DIR / "regles_fiscales.md"
    regles_md = ""
    if regles_path.exists():
        regles_md = regles_path.read_text(encoding="utf-8")

    # Construire le HTML
    meta = cases_data.get("meta", {})
    bareme = cases_data.get("bareme_ir", {})
    categories = cases_data.get("cases", {})
    parts_rules = cases_data.get("regles_parts_fiscales", {})
    ps = cases_data.get("prelevements_sociaux", {})

    # --- Bareme ---
    bareme_html = _render_bareme(bareme)

    # --- Cases par categorie ---
    cases_html = _render_all_cases(categories)

    # --- Parts fiscales ---
    parts_html = _render_parts(parts_rules)

    # --- Regles fiscales (markdown -> HTML basique) ---
    regles_html = _render_markdown(regles_md)

    return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Reference fiscale - Cases 2042 et regles</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Segoe UI',Tahoma,sans-serif; background:#f0f2f5; color:#2c3e50; }}

.topbar {{
    background:linear-gradient(135deg,#1e3a5f,#2980b9); color:white;
    padding:16px 24px; position:sticky; top:0; z-index:100;
    box-shadow:0 2px 8px rgba(0,0,0,0.15);
}}
.topbar-inner {{ max-width:1100px; margin:0 auto; display:flex; align-items:center; gap:16px; flex-wrap:wrap; }}
.topbar h1 {{ font-size:20px; white-space:nowrap; }}
.topbar .meta {{ font-size:12px; opacity:0.7; }}
.search-box {{
    flex:1; min-width:250px; padding:10px 16px;
    border:none; border-radius:8px; font-size:15px;
    outline:none; background:rgba(255,255,255,0.95);
}}
.search-box::placeholder {{ color:#95a5a6; }}
.back-link {{ color:white; text-decoration:none; font-size:14px; opacity:0.8; white-space:nowrap; }}
.back-link:hover {{ opacity:1; }}

.container {{ max-width:1100px; margin:0 auto; padding:20px; }}

.nav {{ display:flex; gap:8px; flex-wrap:wrap; margin-bottom:20px; }}
.nav a {{
    padding:6px 14px; background:white; border:1px solid #ddd;
    border-radius:6px; text-decoration:none; color:#2c3e50;
    font-size:13px; font-weight:500; transition:all 0.2s;
}}
.nav a:hover, .nav a.active {{ background:#2980b9; color:white; border-color:#2980b9; }}

.section {{ background:white; border-radius:12px; padding:20px; margin-bottom:16px; box-shadow:0 1px 4px rgba(0,0,0,0.06); }}
.section h2 {{ color:#1e3a5f; font-size:18px; margin-bottom:14px; border-bottom:2px solid #e8ecf1; padding-bottom:8px; }}
.section h3 {{ color:#2980b9; font-size:15px; margin:16px 0 8px; }}

.case-card {{
    border:1px solid #e8ecf1; border-radius:8px; padding:14px;
    margin-bottom:10px; transition:border-color 0.2s;
}}
.case-card:hover {{ border-color:#2980b9; }}
.case-card.hidden {{ display:none; }}
.case-header {{ display:flex; align-items:center; gap:10px; margin-bottom:6px; }}
.case-num {{
    background:#2980b9; color:white; padding:3px 10px;
    border-radius:6px; font-weight:bold; font-size:14px; white-space:nowrap;
}}
.case-label {{ font-weight:600; font-size:14px; }}
.case-desc {{ font-size:13px; color:#555; line-height:1.5; margin-top:4px; }}
.case-meta {{ font-size:12px; color:#95a5a6; margin-top:6px; }}
.case-meta span {{ margin-right:12px; }}
.case-meta .tag {{
    display:inline-block; padding:1px 8px; border-radius:4px;
    background:#f0f4f8; color:#2c3e50; font-size:11px;
}}

table {{ width:100%; border-collapse:collapse; margin:12px 0; font-size:14px; }}
th,td {{ padding:8px 12px; text-align:left; border-bottom:1px solid #e8ecf1; }}
th {{ background:#f0f4f8; font-weight:600; color:#1e3a5f; }}
.highlight {{ background:#fff8e1; }}

.regles-content {{ font-size:14px; line-height:1.7; }}
.regles-content h2 {{ color:#1e3a5f; font-size:18px; margin:24px 0 10px; border-bottom:2px solid #e8ecf1; padding-bottom:6px; }}
.regles-content h3 {{ color:#2980b9; font-size:15px; margin:16px 0 8px; }}
.regles-content h4 {{ font-size:14px; margin:12px 0 6px; }}
.regles-content table {{ font-size:13px; }}
.regles-content ul {{ padding-left:20px; margin:8px 0; }}
.regles-content li {{ margin-bottom:4px; }}
.regles-content p {{ margin-bottom:8px; }}
.regles-content strong {{ color:#2c3e50; }}
.regles-content code {{ background:#f0f4f8; padding:1px 6px; border-radius:3px; font-size:13px; }}

.count-badge {{
    display:inline-block; background:#e8ecf1; padding:2px 8px;
    border-radius:10px; font-size:12px; color:#555; margin-left:6px;
}}

.case-exemple {{
    background:#f0faf4; border-left:3px solid #27ae60;
    padding:8px 12px; margin-top:8px; border-radius:0 6px 6px 0;
    font-size:13px; color:#2c3e50; line-height:1.5;
}}
.case-exemple strong {{ color:#27ae60; }}

.exemple-calcul {{
    background:#f8fafc; border:1px solid #e8ecf1; border-radius:8px;
    padding:14px; margin-bottom:12px;
}}
.exemple-calcul h4 {{ color:#2980b9; margin-bottom:8px; font-size:14px; }}
.exemple-calcul ol {{ padding-left:20px; font-size:13px; }}
.exemple-calcul li {{ margin-bottom:3px; }}
.exemple-calcul li.highlight {{ background:#fff8e1; font-weight:bold; padding:2px 4px; border-radius:3px; }}

.no-results {{
    text-align:center; padding:40px; color:#95a5a6; font-size:16px;
    display:none;
}}

@media(max-width:640px) {{
    .topbar-inner {{ flex-direction:column; }}
    .container {{ padding:12px; }}
}}
</style>
</head>
<body>

<div class="topbar">
<div class="topbar-inner">
    <div>
        <h1>Reference fiscale 2042</h1>
        <div class="meta">{meta.get('source', 'Declaration des revenus')} | {meta.get('annee_revenus', '?')}</div>
    </div>
    <input type="text" class="search-box" id="search" placeholder="Rechercher une case, un mot-cle... (ex: 1AJ, RSU, LMNP, dividendes)" autofocus>
    <a href="/" class="back-link">Retour a l'agent</a>
</div>
</div>

<div class="container">

<div class="nav" id="nav">
    <a href="#bareme" class="active">Bareme IR</a>
    <a href="#parts">Parts fiscales</a>
    {_render_nav_links(categories)}
    <a href="#regles">Regles detaillees</a>
</div>

<div id="no-results" class="no-results">Aucun resultat pour cette recherche.</div>

<div class="section searchable" id="bareme">
    <h2>Bareme progressif de l'impot sur le revenu</h2>
    {bareme_html}
</div>

<div class="section searchable" id="parts">
    <h2>Quotient familial et nombre de parts</h2>
    {parts_html}
</div>

{cases_html}

<div class="section" id="regles">
    <h2>Regles fiscales detaillees</h2>
    <div class="regles-content">
        {regles_html}
    </div>
</div>

</div>

<script>
const search = document.getElementById('search');
const cards = document.querySelectorAll('.case-card');
const sections = document.querySelectorAll('.section.searchable');
const noResults = document.getElementById('no-results');

search.addEventListener('input', () => {{
    const q = search.value.toLowerCase().trim();
    let visible = 0;

    cards.forEach(card => {{
        const text = card.dataset.search || card.textContent.toLowerCase();
        const match = !q || text.includes(q);
        card.classList.toggle('hidden', !match);
        if (match) visible++;
    }});

    // Cacher les sections vides
    sections.forEach(sec => {{
        const visibleCards = sec.querySelectorAll('.case-card:not(.hidden)');
        const hasContent = visibleCards.length > 0 || !sec.querySelector('.case-card');
        sec.style.display = (!q || hasContent) ? '' : 'none';
    }});

    noResults.style.display = (q && visible === 0) ? 'block' : 'none';
}});
</script>
</body>
</html>"""


def _render_bareme(bareme: dict) -> str:
    if not bareme:
        return "<p>Bareme non disponible.</p>"
    html = f"<p>{bareme.get('description', '')}</p>"
    tranches = bareme.get("tranches", [])
    if tranches:
        html += "<table><thead><tr><th>Tranche de revenu (par part)</th><th>Taux</th></tr></thead><tbody>"
        for t in tranches:
            max_val = f"{t['max']:,.0f} EUR" if t["max"] else "+"
            html += f"<tr><td>De {t['min']:,.0f} EUR a {max_val}</td><td><strong>{t['taux']*100:.0f}%</strong></td></tr>"
        html += "</tbody></table>"

    # Exemples de calcul concrets
    html += "<h3>Exemples de calcul concrets</h3>"
    for ex in EXEMPLES_BAREME:
        html += f'<div class="exemple-calcul"><h4>{ex["titre"]}</h4><ol>'
        for etape in ex["etapes"]:
            css = ' class="highlight"' if etape.startswith("Impot") or "Remboursement" in etape else ""
            html += f"<li{css}>{etape}</li>"
        html += "</ol></div>"

    abat = bareme.get("abattement_10pct", {})
    if abat:
        html += f"<h3>Abattement forfaitaire de 10%</h3><p>{abat.get('description', '')} (min {abat.get('minimum', '?')} EUR, max {abat.get('maximum', '?')} EUR)</p>"

    decote = bareme.get("decote", {})
    if decote:
        html += f"<h3>Decote</h3><p>{decote.get('description', '')}</p>"

    return html


def _render_all_cases(categories: dict) -> str:
    html = ""
    for cat_id, cases in categories.items():
        cat_label = cat_id.replace("_", " ").title()
        case_cards = []
        for case_id, info in cases.items():
            if not isinstance(info, dict):
                continue
            card = _render_case_card(case_id, info)
            if card:
                case_cards.append(card)

        if case_cards:
            html += f'<div class="section searchable" id="cat-{cat_id}">'
            html += f'<h2>{cat_label} <span class="count-badge">{len(case_cards)} cases</span></h2>'
            html += "\n".join(case_cards)
            html += "</div>"
    return html


def _render_case_card(case_id: str, info: dict) -> str:
    libelle = info.get("libelle", info.get("description", ""))
    description = info.get("description", "")
    case_display = info.get("case", case_id)

    if not libelle and not description:
        return ""

    # Construire le texte de recherche
    search_text = f"{case_id} {case_display} {libelle} {description}".lower()
    for key in ("article_cgi", "formulaire", "formulaire_annexe"):
        if info.get(key):
            search_text += f" {info[key]}".lower()

    meta_parts = []
    if info.get("article_cgi"):
        meta_parts.append(f'<span class="tag">{info["article_cgi"]}</span>')
    if info.get("formulaire_annexe"):
        meta_parts.append(f'<span class="tag">Annexe {info["formulaire_annexe"]}</span>')
    if info.get("type"):
        meta_parts.append(f'<span class="tag">{info["type"]}</span>')

    # Infos complementaires
    extras = []
    if info.get("abattement"):
        val = info["abattement"]
        if isinstance(val, float) and val < 1:
            extras.append(f"Abattement : {val*100:.0f}%")
        else:
            extras.append(f"Abattement : {val}")
    if info.get("taux_reduction"):
        extras.append(f"Taux de reduction : {info['taux_reduction']*100:.0f}%")
    if info.get("taux_credit"):
        extras.append(f"Credit d'impot : {info['taux_credit']*100:.0f}%")
    if info.get("plafond_base"):
        extras.append(f"Plafond : {info['plafond_base']:,.0f} EUR")
    if info.get("plafond_par_personne"):
        extras.append(f"Plafond/personne : {info['plafond_par_personne']:,.0f} EUR")
    if info.get("plafond_par_enfant"):
        extras.append(f"Plafond/enfant : {info['plafond_par_enfant']:,.0f} EUR")
    if info.get("seuil"):
        extras.append(f"Seuil : {info['seuil']:,.0f} EUR")
    if info.get("seuil_abattement"):
        extras.append(f"Seuil abattement : {info['seuil_abattement']:,.0f} EUR")

    extras_html = ""
    if extras:
        extras_html = '<div class="case-meta">' + " | ".join(extras) + "</div>"

    # Exemple concret
    exemple = EXEMPLES.get(case_id, EXEMPLES.get(case_display, ""))
    exemple_html = ""
    if exemple:
        exemple_html = f'<div class="case-exemple"><strong>Exemple :</strong> {exemple}</div>'

    return (
        f'<div class="case-card" data-search="{search_text}">'
        f'<div class="case-header"><span class="case-num">{case_display}</span>'
        f'<span class="case-label">{libelle}</span></div>'
        f'{"<div class=case-desc>" + description + "</div>" if description and description != libelle else ""}'
        f'{extras_html}'
        f'{exemple_html}'
        f'{"<div class=case-meta>" + " ".join(meta_parts) + "</div>" if meta_parts else ""}'
        f'</div>'
    )


def _render_parts(parts: dict) -> str:
    if not parts:
        return ""
    html = f"<p>{parts.get('description', '')}</p>"

    base = parts.get("base", {})
    if base:
        html += "<h3>Base</h3><table><thead><tr><th>Situation</th><th>Parts</th></tr></thead><tbody>"
        for sit, val in base.items():
            html += f"<tr><td>{sit.replace('_', ' ').title()}</td><td><strong>{val}</strong></td></tr>"
        html += "</tbody></table>"

    enfants = parts.get("enfants_a_charge", {})
    if enfants:
        html += "<h3>Enfants a charge</h3>"
        html += f"<p>1er enfant : +{enfants.get('1er_enfant', 0.5)} | "
        html += f"2eme : +{enfants.get('2eme_enfant', 0.5)} | "
        html += f"3eme et suivants : +{enfants.get('a_partir_3eme', 1.0)}</p>"
        if enfants.get("description"):
            html += f"<p><em>{enfants['description']}</em></p>"

    demi = parts.get("demi_parts_supplementaires", {})
    if demi:
        html += "<h3>Demi-parts supplementaires</h3><ul>"
        for key, val in demi.items():
            html += f"<li>{key.replace('_', ' ').title()} : +{val} part</li>"
        html += "</ul>"

    return html


def _render_nav_links(categories: dict) -> str:
    links = []
    for cat_id in categories:
        label = cat_id.replace("_", " ").title()
        links.append(f'<a href="#cat-{cat_id}">{label}</a>')
    return "\n".join(links)


def _render_markdown(md: str) -> str:
    """Conversion markdown simplifiee en HTML."""
    if not md:
        return ""
    html = md

    # Tables markdown
    def convert_table(match):
        lines = match.group(0).strip().split("\n")
        if len(lines) < 3:
            return match.group(0)
        headers = [c.strip() for c in lines[0].split("|") if c.strip()]
        rows = []
        for line in lines[2:]:
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if cells:
                rows.append(cells)
        t = "<table><thead><tr>"
        for h in headers:
            t += f"<th>{h}</th>"
        t += "</tr></thead><tbody>"
        for row in rows:
            t += "<tr>"
            for c in row:
                t += f"<td>{c}</td>"
            t += "</tr>"
        t += "</tbody></table>"
        return t

    html = re.sub(r"^\|.+\|\n\|[-| :]+\|\n(?:\|.+\|\n?)+", convert_table, html, flags=re.MULTILINE)

    # Headers
    html = re.sub(r"^#### (.+)$", r"<h4>\1</h4>", html, flags=re.MULTILINE)
    html = re.sub(r"^### (.+)$", r"<h3>\1</h3>", html, flags=re.MULTILINE)
    html = re.sub(r"^## (.+)$", r"<h2>\1</h2>", html, flags=re.MULTILINE)

    # Bold, italic, code
    html = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html)
    html = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html)
    html = re.sub(r"`([^`]+)`", r"<code>\1</code>", html)

    # Lists
    html = re.sub(r"^- (.+)$", r"<li>\1</li>", html, flags=re.MULTILINE)
    html = re.sub(r"(<li>.*</li>\n?)+", r"<ul>\g<0></ul>", html)

    # Paragraphs
    html = re.sub(r"\n\n+", r"</p><p>", html)
    html = "<p>" + html + "</p>"
    html = html.replace("<p></p>", "")
    html = re.sub(r"<p>(<h[234]>)", r"\1", html)
    html = re.sub(r"(</h[234]>)</p>", r"\1", html)
    html = re.sub(r"<p>(<table>)", r"\1", html)
    html = re.sub(r"(</table>)</p>", r"\1", html)
    html = re.sub(r"<p>(<ul>)", r"\1", html)
    html = re.sub(r"(</ul>)</p>", r"\1", html)

    return html
