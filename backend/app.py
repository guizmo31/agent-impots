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
