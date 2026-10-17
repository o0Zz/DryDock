"""Interactive container shell over a WebSocket.

Client -> server: JSON text frames, `{"type": "input", "data": "..."}` or
`{"type": "resize", "cols": 120, "rows": 30}`.
Server -> client: raw terminal output as binary frames.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from urllib.parse import urlparse

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import SESSION_USER_KEY
from app.models.user import User
from app.services import docker_service

logger = logging.getLogger(__name__)

# Not mounted behind the HTTP auth dependency (it expects a Request), so the
# endpoint checks the session itself.
router = APIRouter(prefix="/api/containers", tags=["containers"])

# Application-defined close codes (4000-4999), mirrored in the frontend.
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_UNAVAILABLE = 4404


def _origin_allowed(websocket: WebSocket) -> bool:
    """Block cross-site WebSocket hijacking: the session cookie is also sent
    from other apps on the same host (same-site, different port)."""
    origin = websocket.headers.get("origin")
    if not origin:
        return True  # not a browser
    if origin in settings.cors_origins:
        return True
    host = websocket.headers.get("x-forwarded-host") or websocket.headers.get("host")
    return urlparse(origin).netloc == host


def _session_user(websocket: WebSocket) -> User | None:
    user_id = websocket.session.get(SESSION_USER_KEY)
    if user_id is None:
        return None
    with SessionLocal() as db:
        user = db.get(User, user_id)
        return user if user is not None and user.is_active else None


async def _close(websocket: WebSocket, code: int, reason: str) -> None:
    # Close reasons are capped at 123 bytes by the WebSocket protocol.
    with contextlib.suppress(Exception):
        short = reason.encode("utf-8")[:120].decode("utf-8", "ignore")
        await websocket.close(code=code, reason=short)


@router.websocket("/{container_id}/exec")
async def container_console(
    websocket: WebSocket,
    container_id: str,
    cols: int = Query(default=80, ge=10, le=500),
    rows: int = Query(default=24, ge=5, le=200),
) -> None:
    # Accept first so the close code and reason actually reach the browser.
    await websocket.accept()
    if not _origin_allowed(websocket):
        await _close(websocket, CLOSE_FORBIDDEN, "Origin not allowed")
        return
    user = _session_user(websocket)
    if user is None:
        await _close(websocket, CLOSE_UNAUTHORIZED, "Not authenticated")
        return
    if not user.is_admin:
        await _close(websocket, CLOSE_FORBIDDEN, "Administrator privileges required")
        return

    try:
        session = await run_in_threadpool(
            docker_service.open_exec, container_id, cols=cols, rows=rows
        )
    except docker_service.DockerUnavailable as exc:
        await _close(websocket, CLOSE_UNAVAILABLE, str(exc))
        return
    logger.info("Console opened on container %s by %s", container_id[:12], user.username)

    loop = asyncio.get_running_loop()

    async def pump_output() -> None:
        while True:
            data = await loop.run_in_executor(None, session.read)
            if not data:
                return  # shell exited
            await websocket.send_bytes(data)

    async def pump_input() -> None:
        while True:
            try:
                message = json.loads(await websocket.receive_text())
            except WebSocketDisconnect:
                return
            except (ValueError, TypeError):
                continue
            if not isinstance(message, dict):
                continue
            if message.get("type") == "input" and isinstance(message.get("data"), str):
                await run_in_threadpool(session.write, message["data"].encode("utf-8"))
            elif message.get("type") == "resize":
                with contextlib.suppress(TypeError, ValueError):
                    new_cols, new_rows = int(message["cols"]), int(message["rows"])
                    await run_in_threadpool(session.resize, new_cols, new_rows)

    tasks = {asyncio.create_task(pump_output()), asyncio.create_task(pump_input())}
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        session.close()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Console closed on container %s", container_id[:12])
        await _close(websocket, 1000, "Session ended")
