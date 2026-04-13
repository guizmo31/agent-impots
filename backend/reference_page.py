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

    return (
        f'<div class="case-card" data-search="{search_text}">'
        f'<div class="case-header"><span class="case-num">{case_display}</span>'
        f'<span class="case-label">{libelle}</span></div>'
        f'{"<div class=case-desc>" + description + "</div>" if description and description != libelle else ""}'
        f'{extras_html}'
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
