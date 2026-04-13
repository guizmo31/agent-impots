"""
Agent Impots - Backend FastAPI
Serveur principal orchestrant l'agent fiscal local.
"""
import sys
import os

# Fix encodage Windows — forcer UTF-8 pour stdout/stderr (evite les crashes charmap)
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import json
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from contextlib import asynccontextmanager

from agent import AgentFiscal
from document_parser import DocumentParser
from fiscal_engine import FiscalEngine
from report_generator import ReportGenerator
from session_store import list_sessions, SessionStore

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
OUTPUT_DIR.mkdir(exist_ok=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup/shutdown events."""
    print("=" * 50)
    print("  AGENT IMPOTS - Démarrage")
    print("  http://localhost:8000")
    print("=" * 50)
    existing = list_sessions()
    if existing:
        print(f"  {len(existing)} session(s) sauvegardée(s) trouvée(s)")
    yield
    print("Agent Impôts arrêté.")


app = FastAPI(title="Agent Impôts", lifespan=lifespan)

# Serve frontend
app.mount("/css", StaticFiles(directory=str(BASE_DIR / "frontend" / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(BASE_DIR / "frontend" / "js")), name="js")
app.mount("/img", StaticFiles(directory=str(BASE_DIR / "frontend" / "img")), name="img")
app.mount("/output", StaticFiles(directory=str(OUTPUT_DIR)), name="output")


@app.get("/")
async def index():
    return FileResponse(str(BASE_DIR / "frontend" / "index.html"))


@app.get("/reference")
async def reference():
    """Page de reference fiscale : toutes les cases 2042 + regles."""
    from reference_page import generate_reference_html
    from fastapi.responses import HTMLResponse
    return HTMLResponse(generate_reference_html())


@app.get("/documents")
async def documents_page():
    """Page de visualisation des documents convertis en markdown."""
    from fastapi.responses import HTMLResponse
    from markdown_converter import MarkdownConverter
    mc = MarkdownConverter(str(OUTPUT_DIR))
    markdowns = mc.get_all_markdowns()

    cards = ""
    for md in markdowns:
        # Lire le contenu complet
        md_path = OUTPUT_DIR / "markdown" / md["md_filename"]
        content = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        # Echapper le HTML dans le contenu markdown
        escaped = content.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        cards += f"""
        <div class="doc-card">
            <div class="doc-header" onclick="this.parentElement.classList.toggle('open')">
                <span class="doc-name">{md['source_filename']}</span>
                <span class="doc-size">{md['size']:,} chars</span>
                <span class="doc-toggle">&#9660;</span>
            </div>
            <div class="doc-content"><pre>{escaped}</pre></div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Documents convertis en Markdown</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Segoe UI',Tahoma,sans-serif; background:#f0f2f5; color:#2c3e50; }}
.layout {{ display:flex; height:100vh; }}
.sidebar {{ width:280px; flex-shrink:0; background:linear-gradient(180deg,#1e3a5f,#15293f); display:flex; flex-direction:column; align-items:center; justify-content:center; padding:20px; }}
.sidebar img {{ width:100%; object-fit:contain; border-radius:12px; }}
.main-col {{ flex:1; display:flex; flex-direction:column; min-width:0; overflow:hidden; }}
.topbar {{ background:linear-gradient(135deg,#1e3a5f,#2980b9); color:white; padding:16px 24px; display:flex; justify-content:space-between; align-items:center; }}
.topbar h1 {{ font-size:20px; }}
.topbar a {{ color:white; text-decoration:none; opacity:0.8; }}
.topbar a:hover {{ opacity:1; }}
.content {{ flex:1; overflow-y:auto; padding:20px; }}
.info {{ background:white; border-radius:12px; padding:16px; margin-bottom:16px; box-shadow:0 1px 4px rgba(0,0,0,0.06); font-size:14px; color:#555; }}
.doc-card {{ background:white; border-radius:10px; margin-bottom:8px; box-shadow:0 1px 3px rgba(0,0,0,0.06); overflow:hidden; }}
.doc-header {{ display:flex; align-items:center; padding:12px 16px; cursor:pointer; gap:12px; transition:background 0.2s; }}
.doc-header:hover {{ background:#f8f9fa; }}
.doc-name {{ font-weight:600; flex:1; }}
.doc-size {{ font-size:12px; color:#95a5a6; }}
.doc-toggle {{ font-size:10px; color:#95a5a6; transition:transform 0.2s; }}
.doc-card.open .doc-toggle {{ transform:rotate(180deg); }}
.doc-content {{ display:none; border-top:1px solid #e8ecf1; padding:16px; background:#fafbfc; max-height:600px; overflow:auto; }}
.doc-card.open .doc-content {{ display:block; }}
pre {{ font-size:13px; line-height:1.6; white-space:pre-wrap; word-wrap:break-word; font-family:'Consolas','Courier New',monospace; }}
.empty {{ text-align:center; padding:40px; color:#95a5a6; }}
@media(max-width:768px) {{ .layout {{ flex-direction:column; }} .sidebar {{ width:100%; flex-direction:row; padding:12px; }} .sidebar img {{ width:50px; }} }}
</style></head><body>
<div class="layout">
<aside class="sidebar"><img src="/img/agent-impots.png" alt="Agent IA des impots" /></aside>
<div class="main-col">
<div class="topbar">
    <h1>Documents convertis ({len(markdowns)} fichiers)</h1>
    <a href="javascript:window.close()" onclick="window.close(); return false;">Fermer et revenir a l'agent</a>
</div>
<div class="content">
<div class="info">
    Chaque document d'entree est converti en Markdown avant d'etre analyse par l'IA.
    Vous pouvez verifier ici que le contenu a ete correctement extrait.
    Cliquez sur un document pour voir son contenu.
</div>
{"<div class='empty'>Aucun document converti pour l'instant.</div>" if not markdowns else cards}
</div></div></div></body></html>"""
    return HTMLResponse(html)


# ---- API Sessions ----

@app.get("/api/sessions")
async def get_sessions():
    """Liste toutes les sessions sauvegardées."""
    return JSONResponse(list_sessions())


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str):
    """Supprime une session et tous ses fichiers associes."""
    store = SessionStore(session_id)
    store.delete()
    # Supprimer aussi les fichiers associes (extractions, profil)
    from fiscal_profile import FiscalProfile
    from extraction_store import ExtractionStore
    FiscalProfile(session_id).delete()
    ExtractionStore(session_id).delete()
    if session_id in active_agents:
        del active_agents[session_id]
    return JSONResponse({"status": "deleted"})


@app.post("/api/sessions/{session_id}/save")
async def save_session(session_id: str):
    """Force la sauvegarde complete de la session (etat + extractions + profil)."""
    if session_id in active_agents:
        agent = active_agents[session_id]
        # Persister l'etat courant
        agent._persist()
        # Sauvegarder les extractions sur disque
        if agent.extractions:
            agent.extractions.save()
        # Sauvegarder le profil
        if agent.profile:
            agent.profile.save()
        # Mettre a jour le status page
        if agent.status:
            agent.status.set_state(agent.state)

        docs_count = len(agent.extractions.get_all()) if agent.extractions else 0
        print(f"[SESSION] Sauvegarde forcee : {session_id[:8]}... (etat={agent.state}, {docs_count} docs)")
        return JSONResponse({"status": "saved", "documents_count": docs_count, "state": agent.state})

    # Si l'agent n'est pas en memoire, les fichiers sont deja sur disque
    return JSONResponse({"status": "already_saved"})


# ---- WebSocket ----

active_agents: dict[str, AgentFiscal] = {}


def _create_agent(session_id: str) -> AgentFiscal:
    """Cree ou restaure un agent pour une session donnee."""
    return AgentFiscal(
        document_parser=DocumentParser(),
        fiscal_engine=FiscalEngine(),
        report_generator=ReportGenerator(output_dir=str(OUTPUT_DIR)),
        session_id=session_id,
        output_dir=str(OUTPUT_DIR),
    )


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()

    # Recuperer le nom de session depuis le query param
    session_name = websocket.query_params.get("name", "")

    # Creer ou restaurer l'agent
    if session_id not in active_agents:
        agent = _create_agent(session_id)
        active_agents[session_id] = agent
    else:
        agent = active_agents[session_id]

    # Mettre a jour le nom de la session
    if agent.store:
        current_name = agent.store.get("name", "")
        if session_name:
            agent.store.set("name", session_name)
        elif not current_name:
            from datetime import datetime
            session_name = f"Declaration {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            agent.store.set("name", session_name)
        else:
            session_name = current_name

    # Initialiser le status page avec le nom
    if agent.status and session_name:
        agent.status.set_session_name(session_name)

    # Brancher le callback de progression pour envoyer en temps reel
    async def send_progress(msg: dict):
        await websocket.send_json(msg)

    agent.on_progress = send_progress

    # Envoyer le lien vers la page de status
    status_file = agent.status.get_filename() if agent.status else None
    if status_file:
        await websocket.send_json({
            "type": "status_link",
            "url": f"/output/{status_file}",
        })

    # Envoyer la completion initiale
    pct = agent._compute_completion()
    await websocket.send_json({"type": "completion", "percent": pct})

    # Envoyer le message de bienvenue (ou de reprise)
    await websocket.send_json({
        "type": "assistant",
        "content": agent.get_welcome_message(),
        "state": agent.state,
    })

    # Callback pour envoyer un message intermediaire pendant le traitement
    async def send_message(msg: dict):
        await websocket.send_json(msg)

    agent.on_send = send_message

    try:
        while True:
            data = await websocket.receive_json()
            user_message = data.get("message", "")

            responses = await agent.process_message(user_message)

            for response in responses:
                await websocket.send_json(response)

    except WebSocketDisconnect:
        # L'agent reste en mémoire ET sur disque — on ne le supprime pas
        pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
