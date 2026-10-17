import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from starlette.middleware.sessions import SessionMiddleware

from app.api import (
    auth,
    console,
    containers,
    dashboard,
    images,
    jobs,
    logs,
    networks,
    projects,
    registries,
    scans,
    tokens,
    updates,
    users,
    volumes,
)
from app.api import settings as settings_api
from app.core import log_buffer
from app.core.config import settings
from app.core.database import SessionLocal, init_db
from app.core.security import get_current_user, hash_password
from app.models.user import User
from app.services import (
    compose_service,
    docker_service,
    host_path_service,
    job_service,
    scheduler_service,
)

logging.basicConfig(level=logging.INFO, format=log_buffer.LOG_FORMAT)
log_buffer.install()
logger = logging.getLogger(__name__)


def _seed_admin() -> None:
    """Create the bootstrap admin account if the users table is empty."""
    with SessionLocal() as db:
        if db.scalar(select(User).limit(1)) is not None:
            return
        admin = User(
            username=settings.admin_username,
            hashed_password=hash_password(settings.admin_password),
            is_admin=True,
        )
        db.add(admin)
        db.commit()
        logger.warning(
            "Created bootstrap admin user %r. Change its password immediately.",
            settings.admin_username,
        )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_db()
    _seed_admin()
    host_path_service.setup()
    scheduler_service.start()
    try:
        yield
    finally:
        scheduler_service.shutdown()
        job_service.shutdown()


app = FastAPI(
    title="DryDock",
    version=settings.version,
    lifespan=lifespan,
    # Non-empty when a reverse proxy serves the app under a sub-path.
    root_path=settings.root_path,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Signed session cookie. Must be added after CORS so it runs first on the request.
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.resolve_secret_key(),
    session_cookie=settings.session_cookie,
    max_age=settings.session_max_age,
    same_site="lax",
    https_only=settings.session_https_only,
)

# Service errors that map straight to an HTTP status, so routes need no try/except.
# Matched along the exception's MRO, so DockerNotFound wins over its base class.
_ERROR_STATUS: dict[type[Exception], tuple[int, str]] = {
    docker_service.DockerUnavailable: (503, "Docker unavailable: {}"),
    docker_service.DockerNotFound: (404, "{}"),
    docker_service.ImageNotFound: (404, "image {} not found"),
    docker_service.ImageInUse: (409, "{}"),
    docker_service.VolumeInUse: (409, "{}"),
    docker_service.NetworkInUse: (409, "{}"),
    docker_service.NotAFile: (400, "{}"),
    docker_service.RegistryLoginFailed: (400, "{}"),
    docker_service.ContainerRunning: (409, "{}"),
    docker_service.ContainerConflict: (409, "{}"),
    compose_service.ComposeError: (400, "{}"),
    compose_service.ComposeExists: (409, "{}"),
}


async def _service_error(request: Request, exc: Exception) -> JSONResponse:
    status_code, template = next(
        _ERROR_STATUS[exc_class] for exc_class in type(exc).__mro__ if exc_class in _ERROR_STATUS
    )
    return JSONResponse({"detail": template.format(exc)}, status_code=status_code)


for _exc_type in _ERROR_STATUS:
    app.add_exception_handler(_exc_type, _service_error)

# Public: login/logout/me
app.include_router(auth.router)

# Everything below requires an authenticated session.
_auth = [Depends(get_current_user)]
app.include_router(dashboard.router, dependencies=_auth)
app.include_router(projects.router, dependencies=_auth)
app.include_router(containers.router, dependencies=_auth)
app.include_router(volumes.router, dependencies=_auth)
app.include_router(networks.router, dependencies=_auth)
app.include_router(images.router, dependencies=_auth)
app.include_router(scans.router, dependencies=_auth)
app.include_router(updates.router, dependencies=_auth)
app.include_router(jobs.router, dependencies=_auth)
app.include_router(settings_api.router, dependencies=_auth)
app.include_router(logs.router, dependencies=_auth)
app.include_router(users.router)  # already guarded by require_admin
app.include_router(registries.router, dependencies=_auth)
app.include_router(tokens.router, dependencies=_auth)
app.include_router(console.router)  # WebSocket; checks the session itself


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": settings.version, "repo_path": str(settings.repo_path)}


# Serve the built frontend when it's present (Docker image bakes it into /app/static).
# In dev this directory simply doesn't exist and Vite handles the UI separately.
_STATIC_DIR = Path(__file__).resolve().parent.parent / "static"
if _STATIC_DIR.is_dir():
    _INDEX = _STATIC_DIR / "index.html"
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> FileResponse:
        # /api/* is handled by routers above; anything else falls back to the SPA shell.
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = _STATIC_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_INDEX)
