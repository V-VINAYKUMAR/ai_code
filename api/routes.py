"""
api/routes.py — FastAPI routes: REST, SSE, WebSocket, and parallel execution.
"""

import io
import logging
import zipfile

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from services.orchestrator import Orchestrator

logger = logging.getLogger(__name__)
router = APIRouter()

_orchestrator: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = Orchestrator()
    return _orchestrator


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class TaskRequest(BaseModel):
    task: str
    context_files: list[str] = []


class ParallelRequest(BaseModel):
    steps: list[dict]
    context_files: list[str] = []


# ---------------------------------------------------------------------------
# REST — one-shot
# ---------------------------------------------------------------------------

@router.post("/agent/run", summary="Run a task synchronously")
async def run_agent(req: TaskRequest):
    orch    = get_orchestrator()
    results = await orch.run(req.task, req.context_files)
    return {"results": results}
@router.get("/agent/download", summary="Download generated project")
async def download_project():
    import io
    import zipfile
    from pathlib import Path
    from fastapi.responses import StreamingResponse

    output_root = Path.cwd() / "generated_project"

    if not output_root.exists():
        return {"error": "No generated project available. Run the agents first."}

    files = [
        path for path in output_root.rglob("*")
        if path.is_file()
    ]

    if not files:
        return {"error": "Generated project is empty. Run the agents first."}

    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(
        zip_buffer,
        "w",
        zipfile.ZIP_DEFLATED
    ) as zip_file:
        for file_path in files:
            archive_name = file_path.relative_to(output_root)
            zip_file.write(file_path, archive_name)

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=generated_project.zip"
        }
    )


# ---------------------------------------------------------------------------
# Parallel execution endpoint
# ---------------------------------------------------------------------------

@router.post("/agent/run_parallel", summary="Run multiple steps in parallel")
async def run_parallel_endpoint(req: ParallelRequest):
    """
    Execute multiple independent steps concurrently.
    
    Example request body:
    {
        "steps": [
            {"agent": "coder", "description": "Create user model"},
            {"agent": "coder", "description": "Create API routes"},
            {"agent": "tool", "tool_name": "pip_install", "tool_params": {"package": "fastapi"}}
        ],
        "context_files": ["main.py"]
    }
    """
    orch = get_orchestrator()
    results = await orch.run_parallel(req.steps, req.context_files)
    return {"results": results}


# ---------------------------------------------------------------------------
# SSE — streaming
# ---------------------------------------------------------------------------

@router.post("/agent/stream", summary="Stream task output via SSE")
async def run_agent_stream(req: TaskRequest):
    """
    Streams output token-by-token as Server-Sent Events.
    The client reads these via fetch() + ReadableStream — not EventSource,
    because task payload lives in the POST body, not the URL.
    """
    orch = get_orchestrator()

    async def event_generator():
        async for chunk in orch.run_streaming(req.task, req.context_files):
            yield {"data": chunk.replace("\n", "↵")}

    return EventSourceResponse(event_generator())


# ---------------------------------------------------------------------------
# WebSocket — bidirectional interactive
# ---------------------------------------------------------------------------

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    Bidirectional WebSocket.

    Client sends:  {"task": "...", "context_files": [...]}
    Server streams: text chunks, ending with "__DONE__"
    """
    await websocket.accept()
    try:
        while True:
            data           = await websocket.receive_json()
            task           = data.get("task", "")
            context_files  = data.get("context_files", [])

            if not task:
                await websocket.send_text("❌ No task provided.")
                continue

            orch = get_orchestrator()
            try:
                async for chunk in orch.run_streaming(task, context_files):
                    await websocket.send_text(chunk)
                await websocket.send_text("__DONE__")
            except Exception as exc:
                logger.exception("Orchestrator error during WebSocket session")
                await websocket.send_text(f"❌ Error: {exc}")

    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected.")
