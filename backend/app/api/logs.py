from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from starlette.responses import StreamingResponse

from app.core import log_buffer
from app.core.security import require_admin
from app.services import compose_service, docker_service, repo_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/logs", tags=["logs"])

SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
APP_LOG_POLL_SECONDS = 1.0


def _format_sse(data: str, event: str | None = None) -> bytes:
    lines = [f"event: {event}"] if event else []
    for line in data.splitlines() or [""]:
        lines.append(f"data: {line}")
    lines.append("")
    return ("\n".join(lines) + "\n").encode("utf-8")


async def _pump(
    read_line: Callable[[], bytes | None], close: Callable[[], None], label: str
) -> AsyncIterator[bytes]:
    """Turn a blocking line reader into an SSE stream."""
    loop = asyncio.get_running_loop()
    yield _format_sse("connected", event="open")
    try:
        while True:
            chunk = await loop.run_in_executor(None, read_line)
            if chunk is None:
                break
            text = chunk.decode("utf-8", errors="replace").rstrip("\n")
            if not text:
                continue
            yield _format_sse(text)
    except asyncio.CancelledError:
        logger.info("Log stream cancelled for %s", label)
        raise
    finally:
        with contextlib.suppress(Exception):  # best-effort cleanup
            close()
        yield _format_sse("closed", event="close")


def _container_stream(container_id: str, tail: int) -> AsyncIterator[bytes]:
    stream = docker_service.stream_logs(container_id, tail=tail)

    def read_line() -> bytes | None:
        try:
            return next(stream)
        except StopIteration:
            return None

    return _pump(read_line, stream.close, container_id)


def _project_stream(
    compose_path: Path, tail: int, label: str, project_name: str | None
) -> AsyncIterator[bytes]:
    process = compose_service.stream_logs(compose_path, tail=tail, project_name=project_name)

    def read_line() -> bytes | None:
        assert process.stdout is not None
        line = process.stdout.readline()
        return line or None

    def close() -> None:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except Exception:  # noqa: BLE001 - fall through to kill
                process.kill()
        if process.stdout is not None:
            process.stdout.close()

    return _pump(read_line, close, label)


@router.get("/container/{container_id}")
async def stream_container_logs(
    container_id: str, tail: int = Query(default=200, ge=0, le=10_000)
) -> StreamingResponse:
    docker_service.get_container(container_id)
    return StreamingResponse(
        _container_stream(container_id, tail),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get("/project/{project_id}")
async def stream_project_logs(
    project_id: str, tail: int = Query(default=200, ge=0, le=10_000)
) -> StreamingResponse:
    project = repo_service.find_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")
    project = repo_service.attach_containers([project])[0]

    try:
        stream = _project_stream(
            Path(project.compose_path),
            tail,
            project.name,
            repo_service.compose_project_name(project),
        )
    except compose_service.ComposeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return StreamingResponse(stream, media_type="text/event-stream", headers=SSE_HEADERS)


async def _app_stream(tail: int) -> AsyncIterator[bytes]:
    yield _format_sse("connected", event="open")
    entries = log_buffer.buffer.tail(tail)
    last_seq = entries[-1][0] if entries else log_buffer.buffer.last_seq
    while True:
        for _, line in entries:
            yield _format_sse(line)
        if entries:
            last_seq = entries[-1][0]
        await asyncio.sleep(APP_LOG_POLL_SECONDS)
        entries = log_buffer.buffer.since(last_seq)


@router.get("/app", dependencies=[Depends(require_admin)])
async def stream_app_logs(
    tail: int = Query(default=500, ge=0, le=log_buffer.MAX_LINES),
) -> StreamingResponse:
    """DryDock's own backend logs (scans, jobs, errors), newest lines live."""
    return StreamingResponse(_app_stream(tail), media_type="text/event-stream", headers=SSE_HEADERS)
