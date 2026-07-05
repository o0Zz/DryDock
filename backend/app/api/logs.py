from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from starlette.responses import StreamingResponse

from app.services import docker_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])


def _format_sse(data: str, event: str | None = None) -> bytes:
    lines = [f"event: {event}"] if event else []
    for line in data.splitlines() or [""]:
        lines.append(f"data: {line}")
    lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")


async def _iter_logs(container_id: str, tail: int) -> AsyncIterator[bytes]:
    loop = asyncio.get_running_loop()
    try:
        stream = docker_service.stream_logs(container_id, tail=tail)
    except docker_service.DockerUnavailable as exc:
        yield _format_sse(str(exc), event="error")
        return

    def _next() -> bytes | None:
        try:
            return next(stream)
        except StopIteration:
            return None

    yield _format_sse("connected", event="open")
    try:
        while True:
            chunk = await loop.run_in_executor(None, _next)
            if chunk is None:
                break
            text = chunk.decode("utf-8", errors="replace").rstrip("\n")
            if not text:
                continue
            yield _format_sse(text)
    except asyncio.CancelledError:
        logger.info("Log stream cancelled for %s", container_id)
        raise
    finally:
        try:
            stream.close()
        except Exception:  # noqa: BLE001 — best-effort cleanup
            pass
        yield _format_sse("closed", event="close")


@router.get("/container/{container_id}")
async def stream_container_logs(
    container_id: str, tail: int = Query(default=200, ge=0, le=10_000)
) -> StreamingResponse:
    try:
        docker_service.get_container(container_id)
    except docker_service.DockerUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return StreamingResponse(
        _iter_logs(container_id, tail),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
