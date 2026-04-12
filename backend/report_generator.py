"""
Générateur de rapport fiscal détaillé en HTML.
"""
import json
from datetime import datetime
from pathlib import Path


class ReportGenerator:
    def __init__(self, output_dir: str):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    def generate(self, result: dict, documents: list[dict], profile: dict) -> str:
        """Génère un rapport HTML détaillé et retourne le chemin du fichier."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"rapport_fiscal_{timestamp}.html"
        filepath = self.output_dir / filename

        html = self._render_html(result, documents, profile)
        filepath.write_text(html, encoding="utf-8")

        # Sauvegarder aussi le JSON brut
        json_path = self.output_dir / f"rapport_fiscal_{timestamp}.json"
        json_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

        return filename

    def _render_html(self, result: dict, documents: list[dict], profile: dict) -> str:
        situation = result.get("situation", {})
        cases = result.get("cases", [])
        calcul = result.get("calcul_impot", {})
        remarques = result.get("remarques", [])

        def fmt(v):
            if isinstance(v, (int, float)):
                return f"{v:,.2f} €".replace(",", " ").replace(".", ",").replace(" ", "&nbsp;")
            return str(v)

        # Cases rows
        cases_rows = ""
        for c in cases:
            cases_rows += f"""
            <tr>
                <td class="case-num">{c.get('case', '?')}</td>
                <td>{c.get('libelle', '')}</td>
                <td class="montant">{fmt(c.get('montant', 0))}</td>
                <td>{c.get('justification', '')}</td>
                <td>{c.get('source', '')}</td>
            </tr>"""

        # Documents list
        docs_list = ""
        for doc in documents:
            docs_list += f"<li><strong>{doc.get('filename', '?')}</strong> ({doc.get('extension', '?')})</li>\n"

        # Profile summary
        profile_items = ""
        for key, value in profile.items():
            if key.startswith("q") and isinstance(value, dict):
                profile_items += f"""
                <tr>
                    <td>{value.get('question', '')}</td>
                    <td>{value.get('answer', '')}</td>
                </tr>"""

        # Remarques
        remarques_html = ""
        for r in remarques:
            remarques_html += f"<li>{r}</li>\n"

        return f"""<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Rapport Fiscal - Agent Impôts</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #f5f7fa;
            color: #2c3e50;
            line-height: 1.6;
            padding: 40px;
        }}
        .container {{ max-width: 1000px; margin: 0 auto; }}
        .header {{
            background: linear-gradient(135deg, #1e3a5f, #2980b9);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 30px;
        }}
        .header h1 {{ font-size: 28px; margin-bottom: 8px; }}
        .header p {{ opacity: 0.85; font-size: 14px; }}
        .section {{
            background: white;
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }}
        .section h2 {{
            color: #1e3a5f;
            font-size: 20px;
            margin-bottom: 16px;
            padding-bottom: 8px;
            border-bottom: 2px solid #e8ecf1;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 12px;
        }}
        th, td {{
            padding: 10px 14px;
            text-align: left;
            border-bottom: 1px solid #e8ecf1;
            font-size: 14px;
        }}
        th {{
            background: #f0f4f8;
            font-weight: 600;
            color: #1e3a5f;
        }}
        .case-num {{
            font-weight: bold;
            color: #2980b9;
            font-size: 16px;
        }}
        .montant {{
            font-weight: bold;
            color: #27ae60;
            white-space: nowrap;
        }}
        .summary-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }}
        .summary-item {{
            display: flex;
            justify-content: space-between;
            padding: 12px 16px;
            background: #f8fafc;
            border-radius: 8px;
            border-left: 4px solid #2980b9;
        }}
        .summary-item.total {{
            border-left-color: #e74c3c;
            background: #fef9f9;
            font-weight: bold;
            font-size: 16px;
        }}
        .summary-item.positive {{
            border-left-color: #27ae60;
            background: #f0faf4;
        }}
        .summary-label {{ color: #5a6c7d; }}
        .summary-value {{ font-weight: 600; }}
        .warning {{
            background: #fff8e1;
            border: 1px solid #ffc107;
            border-radius: 8px;
            padding: 16px;
            margin-top: 16px;
        }}
        .warning h3 {{ color: #e65100; margin-bottom: 8px; }}
        ul {{ padding-left: 20px; }}
        li {{ margin-bottom: 4px; }}
        .footer {{
            text-align: center;
            color: #95a5a6;
            font-size: 12px;
            margin-top: 40px;
        }}
        @media print {{
            body {{ background: white; padding: 20px; }}
            .section {{ box-shadow: none; border: 1px solid #ddd; }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>Rapport de Déclaration Fiscale</h1>
            <p>Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')} — Agent Impôts (100% local)</p>
            <p>Situation : {situation.get('situation_familiale', 'N/A')} — {situation.get('parts', '?')} part(s) fiscale(s)</p>
        </div>

        <div class="section">
            <h2>Documents analysés</h2>
            <ul>{docs_list}</ul>
        </div>

        <div class="section">
            <h2>Profil du contribuable</h2>
            <table>
                <thead><tr><th>Question</th><th>Réponse</th></tr></thead>
                <tbody>{profile_items}</tbody>
            </table>
        </div>

        <div class="section">
            <h2>Cases à remplir (Formulaire 2042)</h2>
            <table>
                <thead>
                    <tr>
                        <th>Case</th>
                        <th>Libellé</th>
                        <th>Montant</th>
                        <th>Justification</th>
                        <th>Source</th>
                    </tr>
                </thead>
                <tbody>{cases_rows}</tbody>
            </table>
        </div>

        <div class="section">
            <h2>Calcul de l'impôt</h2>
            <div class="summary-grid">
                <div class="summary-item">
                    <span class="summary-label">Revenu brut global</span>
                    <span class="summary-value">{fmt(calcul.get('revenu_brut_global', 0))}</span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Abattement 10%</span>
                    <span class="summary-value">- {fmt(calcul.get('abattement_10_pct', 0))}</span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Revenu net imposable</span>
                    <span class="summary-value">{fmt(calcul.get('revenu_net_imposable', 0))}</span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Nombre de parts</span>
                    <span class="summary-value">{calcul.get('nombre_parts', '?')}</span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Quotient familial</span>
                    <span class="summary-value">{fmt(calcul.get('quotient_familial', 0))}</span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Impôt brut</span>
                    <span class="summary-value">{fmt(calcul.get('impot_brut', 0))}</span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Décote</span>
                    <span class="summary-value">- {fmt(calcul.get('decote', 0))}</span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Impôt net</span>
                    <span class="summary-value">{fmt(calcul.get('impot_net', 0))}</span>
                </div>
                <div class="summary-item">
                    <span class="summary-label">Prélèvement à la source payé</span>
                    <span class="summary-value">- {fmt(calcul.get('prelev_source_deja_paye', 0))}</span>
                </div>
                <div class="summary-item {'total' if calcul.get('solde', 0) > 0 else 'positive'}">
                    <span class="summary-label">{'Solde à payer' if calcul.get('solde', 0) >= 0 else 'Remboursement estimé'}</span>
                    <span class="summary-value">{fmt(abs(calcul.get('solde', 0)))}</span>
                </div>
            </div>
            <p style="margin-top: 16px; font-size: 13px; color: #7f8c8d;">
                <strong>Détail du barème :</strong> {calcul.get('detail_bareme', 'N/A')}
            </p>
        </div>

        <div class="section warning">
            <h3>Avertissements et remarques</h3>
            <ul>{remarques_html}</ul>
        </div>

        <div class="footer">
            <p>Agent Impôts — Outil d'aide à la déclaration fiscale (100% local)</p>
            <p>Ce document est une estimation et ne constitue pas un avis fiscal professionnel.</p>
        </div>
    </div>
</body>
</html>"""
