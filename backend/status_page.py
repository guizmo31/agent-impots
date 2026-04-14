"""
Page de status HTML temps reel — vue d'ensemble de la declaration en cours.

Ce fichier HTML est regenere a chaque etape significative de l'agent :
- Ingestion : chaque document extrait ajoute une ligne
- Validation : chaque reponse utilisateur enrichit le profil
- Calcul : les cases 2042 apparaissent au fur et a mesure
- Verification : les alertes sont ajoutees

L'utilisateur peut ouvrir ce fichier a tout moment pour voir l'avancement.
"""
import json
from datetime import datetime
from pathlib import Path


class StatusPage:
    """Genere et met a jour la page de status HTML.
    Lit les donnees directement depuis les fichiers de session (pas de copie en memoire)."""

    def __init__(self, output_dir: str, session_id: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        self.session_id = session_id
        self.filepath = self.output_dir / f"status_{session_id[:8]}.html"
        self.sessions_dir = Path(__file__).resolve().parent.parent / "sessions"

        # Seules les donnees NON persistees ailleurs sont gardees en memoire
        self.session_name = ""
        self.state = "initialisation"
        self.documents: list[dict] = []
        self.cases: list[dict] = []
        self.calcul: dict = {}
        self.warnings: list[str] = []
        self.report_path: str = ""

    def set_session_name(self, name: str):
        self.session_name = name
        self._write()

    def set_state(self, state: str):
        self.state = state
        self._write()

    def add_document(self, filename: str, status: str, doc_type: str = "", detail: str = ""):
        """Ajoute ou met a jour un document dans la liste."""
        # Mettre a jour si deja present
        for d in self.documents:
            if d["filename"] == filename:
                d["status"] = status
                d["type"] = doc_type
                d["detail"] = detail
                self._write()
                return
        self.documents.append({
            "filename": filename,
            "status": status,
            "type": doc_type,
            "detail": detail,
        })
        self._write()

    def refresh(self):
        """Force un rafraichissement du HTML (relit les fichiers de session)."""
        self._write()

    def set_cases(self, cases: list[dict]):
        self.cases = cases
        self._write()

    def set_calcul(self, calcul: dict):
        self.calcul = calcul
        self._write()

    def set_warnings(self, warnings: list[str]):
        self.warnings = warnings
        self._write()

    def set_report_path(self, path: str):
        self.report_path = path
        self._write()

    def get_filename(self) -> str:
        return self.filepath.name

    # ------------------------------------------------------------------
    # Rendu HTML
    # ------------------------------------------------------------------

    def _write(self):
        html = self._render()
        self.filepath.write_text(html, encoding="utf-8")

    def _load_profile(self) -> dict:
        """Charge le profil depuis le fichier de session."""
        path = self.sessions_dir / f"{self.session_id}_profile.json"
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _load_questions(self) -> list[dict]:
        """Charge les questions/reponses depuis l'historique de la session."""
        path = self.sessions_dir / f"{self.session_id}.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []

        # Extraire les Q/R de l'historique de conversation
        history = data.get("conversation_history", [])
        questions = []
        pending_question = None
        for msg in history:
            content = msg.get("content", "")
            role = msg.get("role", "")
            if role == "assistant" and "**Question " in content:
                # Extraire la question apres "Question X/Y :\n"
                parts = content.split(":\n", 1)
                if len(parts) > 1:
                    pending_question = parts[1].strip()
            elif role == "user" and pending_question:
                questions.append({"question": pending_question, "answer": content})
                pending_question = None
        return questions

    def _load_documents(self) -> list[dict]:
        """Charge les documents depuis le fichier _extractions.json."""
        path = self.sessions_dir / f"{self.session_id}_extractions.json"
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            docs = []
            for ext in data.get("extractions", []):
                docs.append({
                    "filename": ext.get("doc_id", "?"),
                    "status": "ok",
                    "type": ext.get("type_document", ""),
                    "detail": ext.get("resume", "")[:80],
                })
            return docs
        except (json.JSONDecodeError, OSError):
            return []

    def _render(self) -> str:
        now = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        page_title = "Ma declaration fiscale en direct"

        # Charger le nom de session depuis le fichier
        session_file = self.sessions_dir / f"{self.session_id}.json"
        if not self.session_name and session_file.exists():
            try:
                sdata = json.loads(session_file.read_text(encoding="utf-8"))
                self.session_name = sdata.get("name", "")
            except (json.JSONDecodeError, OSError):
                pass
        subtitle = self.session_name or ""

        # Charger les donnees fraiches depuis les fichiers de session
        profile = self._load_profile()
        questions = self._load_questions()
        documents_from_store = self._load_documents()

        # Fusionner : le store fait autorite (status "ok" definitif),
        # la memoire ne sert que pour les docs en cours ("processing")
        all_docs = {d["filename"]: d for d in documents_from_store}
        for d in self.documents:
            fname = d["filename"]
            if fname not in all_docs:
                # Document pas dans le store : progression temps reel
                all_docs[fname] = d
            elif d["status"] == "processing":
                # En cours de traitement : garder le status temps reel
                all_docs[fname] = d
            # Sinon : le store a le bon status ("ok"), on le garde
        documents = list(all_docs.values())

        state_labels = {
            "initialisation": ("Initialisation", "#95a5a6"),
            "welcome": ("En attente", "#95a5a6"),
            "ingestion": ("Analyse des documents", "#e67e22"),
            "parallel": ("Analyse + questions", "#e67e22"),
            "synthese": ("Synthese du dossier", "#3498db"),
            "validation": ("Questions complementaires", "#3498db"),
            "confirmation": ("Confirmation du dossier", "#e67e22"),
            "calcul": ("Calcul fiscal", "#9b59b6"),
            "verification": ("Verification", "#9b59b6"),
            "done": ("Termine", "#27ae60"),
        }
        state_label, state_color = state_labels.get(self.state, (self.state, "#95a5a6"))

        # Documents (fusion memoire + fichier)
        docs_html = ""
        docs_ok = sum(1 for d in documents if d["status"] == "ok")
        docs_err = sum(1 for d in documents if d["status"] == "error")
        docs_skip = sum(1 for d in documents if d["status"] == "skip")
        docs_processing = sum(1 for d in documents if d["status"] == "processing")

        if documents:
            docs_html = "<table><thead><tr><th>Fichier</th><th>Statut</th><th>Type</th><th>Detail</th><th>Markdown</th></tr></thead><tbody>"
            for d in documents:
                icon = {"ok": "&#10003;", "error": "&#10007;", "skip": "&#8631;", "processing": "&#9881;"}.get(d["status"], "?")
                color = {"ok": "#27ae60", "error": "#e74c3c", "skip": "#95a5a6", "processing": "#e67e22"}.get(d["status"], "#333")
                # Lien vers le markdown editable
                fname = d["filename"]
                md_name = Path(fname).stem + ".md"
                md_link = f'<a href="/documents/{md_name}" target="_blank" style="color:#2980b9;font-weight:600">Editer</a>' if d["status"] == "ok" else ""
                docs_html += (
                    f'<tr><td>{fname}</td>'
                    f'<td style="color:{color};font-weight:bold">{icon} {d["status"]}</td>'
                    f'<td>{d["type"]}</td><td>{d["detail"][:60]}</td>'
                    f'<td>{md_link}</td></tr>'
                )
            docs_html += "</tbody></table>"

        # Profil (lu depuis le fichier de session)
        profile_html = ""
        if profile:
            foyer = profile.get("foyer", {})
            revenus = profile.get("revenus", {})
            profile_html = '<div class="profile-grid">'

            if foyer.get("situation"):
                parts = foyer.get("nb_parts", "?")
                detail = foyer.get("detail_parts", "")
                enfants_min = foyer.get("nb_enfants_mineurs", 0)
                enfants_maj = foyer.get("nb_enfants_majeurs_rattaches", 0)
                enfants_txt = f"{enfants_min} mineur(s)"
                if enfants_maj:
                    enfants_txt += f" + {enfants_maj} majeur(s)"
                profile_html += f'<div class="profile-card"><h4>Foyer</h4><p>{foyer["situation"]}, {enfants_txt}, {parts} part(s)</p>'
                if detail:
                    profile_html += f'<p style="font-size:12px;color:#666">{detail}</p>'
                profile_html += '</div>'

            salaires = revenus.get("salaires", [])
            if salaires:
                total = sum(s.get("net_imposable", 0) for s in salaires)
                profile_html += f'<div class="profile-card"><h4>Salaires</h4><p>{total:,.0f} EUR net imposable</p></div>'

            foncier = revenus.get("foncier_nu", [])
            if foncier:
                profile_html += f'<div class="profile-card"><h4>Foncier</h4><p>{len(foncier)} bien(s)</p></div>'

            societes = revenus.get("societe", [])
            if societes:
                noms = ", ".join(s.get("nom", s.get("type", "?")) for s in societes)
                profile_html += f'<div class="profile-card"><h4>Societes</h4><p>{noms}</p></div>'

            cm = revenus.get("capitaux_mobiliers", {})
            if cm.get("dividendes") or cm.get("interets"):
                profile_html += f'<div class="profile-card"><h4>Capitaux mobiliers</h4><p>Dividendes: {cm.get("dividendes",0):,.0f} EUR, Interets: {cm.get("interets",0):,.0f} EUR</p></div>'

            profile_html += "</div>"

        # Questions (lues depuis l'historique de la session)
        questions_html = ""
        if questions:
            questions_html = "<table><thead><tr><th>#</th><th>Question</th><th>Reponse</th></tr></thead><tbody>"
            for i, q in enumerate(questions):
                answer = q["answer"] or '<em style="color:#95a5a6">en attente...</em>'
                questions_html += f'<tr><td>{i+1}</td><td>{q["question"][:120]}</td><td>{answer}</td></tr>'
            questions_html += "</tbody></table>"

        # Cases 2042
        cases_html = ""
        if self.cases:
            cases_html = "<table><thead><tr><th>Case</th><th>Libelle</th><th>Montant</th><th>Justification</th></tr></thead><tbody>"
            for c in self.cases:
                montant = c.get("montant", 0)
                montant_str = f"{montant:,.2f} EUR" if isinstance(montant, (int, float)) else str(montant)
                cases_html += (
                    f'<tr><td class="case-num">{c.get("case","?")}</td>'
                    f'<td>{c.get("libelle","")}</td>'
                    f'<td class="montant">{montant_str}</td>'
                    f'<td>{str(c.get("justification",""))[:100]}</td></tr>'
                )
            cases_html += "</tbody></table>"

        # Calcul
        calcul_html = ""
        if self.calcul:
            def fmt(v):
                return f"{v:,.2f} EUR" if isinstance(v, (int, float)) else str(v)
            calcul_html = '<div class="calcul-grid">'
            for key in ["revenu_brut_global", "abattement_10_pct", "revenu_net_imposable",
                        "nombre_parts", "quotient_familial", "impot_brut", "decote",
                        "impot_net", "prelev_source_deja_paye", "solde"]:
                if key in self.calcul:
                    label = key.replace("_", " ").capitalize()
                    val = self.calcul[key]
                    css = ""
                    if key == "solde":
                        css = ' style="font-size:18px;font-weight:bold"'
                        if isinstance(val, (int,float)):
                            label = "Solde a payer" if val > 0 else "Remboursement estime"
                            val = abs(val)
                    calcul_html += f'<div class="calcul-item"{css}><span>{label}</span><span>{fmt(val)}</span></div>'
            calcul_html += "</div>"

        # Warnings
        warnings_html = ""
        if self.warnings:
            warnings_html = '<div class="warnings"><h4>Alertes</h4><ul>'
            for w in self.warnings:
                warnings_html += f"<li>{w}</li>"
            warnings_html += "</ul></div>"

        # Rapport
        report_html = ""
        if self.report_path:
            report_html = (
                f'<div class="report-links">'
                f'<a href="{self.report_path}.pdf" class="btn btn-pdf">Telecharger le PDF</a>'
                f'<a href="{self.report_path}.html" class="btn btn-html">Voir le rapport HTML</a>'
                f'</div>'
            )

        return f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>{page_title}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Segoe UI',Tahoma,sans-serif; background:#f0f2f5; color:#2c3e50; }}
.layout {{ display:flex; height:100vh; }}
.sidebar {{ width:280px; flex-shrink:0; background:linear-gradient(180deg,#1e3a5f,#15293f); display:flex; flex-direction:column; align-items:center; justify-content:center; padding:20px; }}
.sidebar img {{ width:100%; object-fit:contain; border-radius:12px; }}
.main-col {{ flex:1; display:flex; flex-direction:column; min-width:0; overflow-y:auto; }}
.container {{ max-width:1000px; margin:0 auto; padding:20px; }}
@media(max-width:768px) {{ .layout {{ flex-direction:column; }} .sidebar {{ width:100%; flex-direction:row; padding:12px; }} .sidebar img {{ width:50px; }} }}
.header {{ background:linear-gradient(135deg,#1e3a5f,#2980b9); color:white; padding:24px; border-radius:12px; margin-bottom:20px; display:flex; justify-content:space-between; align-items:center; }}
.header h1 {{ font-size:22px; }}
.header .meta {{ font-size:13px; opacity:0.8; text-align:right; }}
.state-badge {{ display:inline-block; padding:4px 14px; border-radius:12px; font-weight:600; font-size:13px; color:white; background:{state_color}; }}
.section {{ background:white; border-radius:12px; padding:20px; margin-bottom:16px; box-shadow:0 2px 8px rgba(0,0,0,0.06); }}
.section h3 {{ color:#1e3a5f; margin-bottom:12px; font-size:16px; border-bottom:2px solid #e8ecf1; padding-bottom:6px; }}
.stats {{ display:flex; gap:12px; margin-bottom:16px; flex-wrap:wrap; }}
.stat {{ padding:8px 16px; border-radius:8px; font-size:14px; font-weight:600; }}
.stat-ok {{ background:#e8f8f0; color:#27ae60; }}
.stat-err {{ background:#fdecea; color:#e74c3c; }}
.stat-skip {{ background:#f0f0f0; color:#95a5a6; }}
.stat-proc {{ background:#fef5e7; color:#e67e22; }}
table {{ width:100%; border-collapse:collapse; font-size:13px; }}
th,td {{ padding:8px 10px; text-align:left; border-bottom:1px solid #e8ecf1; }}
th {{ background:#f0f4f8; font-weight:600; color:#1e3a5f; }}
.case-num {{ font-weight:bold; color:#2980b9; font-size:15px; }}
.montant {{ font-weight:bold; color:#27ae60; white-space:nowrap; }}
.profile-grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); gap:12px; }}
.profile-card {{ background:#f8fafc; border-radius:8px; padding:12px; border-left:4px solid #2980b9; }}
.profile-card h4 {{ color:#1e3a5f; font-size:13px; margin-bottom:4px; }}
.profile-card p {{ font-size:14px; }}
.calcul-grid {{ display:flex; flex-direction:column; gap:8px; }}
.calcul-item {{ display:flex; justify-content:space-between; padding:8px 12px; background:#f8fafc; border-radius:6px; }}
.warnings {{ background:#fff8e1; border:1px solid #ffc107; border-radius:8px; padding:14px; }}
.warnings h4 {{ color:#e65100; margin-bottom:6px; }}
.warnings li {{ margin-bottom:4px; font-size:14px; }}
.btn {{ display:inline-block; padding:10px 20px; color:white; text-decoration:none; border-radius:8px; font-weight:600; font-size:14px; margin-right:10px; }}
.btn-pdf {{ background:#c0392b; }}
.btn-html {{ background:#2980b9; }}
.report-links {{ margin-top:16px; }}
.footer {{ text-align:center; color:#95a5a6; font-size:12px; margin-top:20px; }}
</style>
</head>
<body>
<div class="layout">
<aside class="sidebar"><img src="/img/agent-impots.png" alt="Agent IA des impots" /></aside>
<div class="main-col">
<div class="container">
<div class="header">
    <div>
        <h1>{page_title}</h1>
        <div>{subtitle} <span class="state-badge">{state_label}</span></div>
    </div>
    <div class="meta">Mis a jour : {now}<br>Rechargez la page pour actualiser</div>
</div>

<div class="section">
    <h3>Documents ({len(documents)})</h3>
    <div class="stats">
        <span class="stat stat-ok">{docs_ok} extraits</span>
        <span class="stat stat-err">{docs_err} erreurs</span>
        <span class="stat stat-skip">{docs_skip} ignores</span>
        {"<span class='stat stat-proc'>" + str(docs_processing) + " en cours</span>" if docs_processing else ""}
    </div>
    {docs_html}
</div>

{"<div class='section'><h3>Profil fiscal</h3>" + profile_html + "</div>" if profile_html else ""}

{"<div class='section'><h3>Questions / Reponses</h3>" + questions_html + "</div>" if questions_html else ""}

{"<div class='section'><h3>Cases a remplir (Formulaire 2042)</h3>" + cases_html + "</div>" if cases_html else ""}

{"<div class='section'><h3>Calcul de l'impot</h3>" + calcul_html + "</div>" if calcul_html else ""}

{warnings_html}

{report_html}

<div class="footer">Agent IA des impots "100% local" (sans internet)</div>
</div>
</div>
</div>
</body>
</html>"""
