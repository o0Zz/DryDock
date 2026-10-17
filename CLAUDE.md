# DryDock

A small, self-hosted web UI for Docker Compose stacks on a homelab or Raspberry Pi. It is a focused alternative to Portainer. A mounted folder of Compose files is the source of truth. DryDock lists the stacks, edits them, runs them, scans their images for CVEs and checks for image updates.

The repo folder is named `HarborGuard`, an earlier name. The product, the env prefix (`DRYDOCK_`), the package and the image are all **DryDock**.

`README.md` is the short, user-facing page (features, quick start, config). Contributor detail lives here. Keep both in sync when behaviour changes.

## Stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2 (sync) on SQLite, Alembic, docker-py, APScheduler, httpx. Managed with `uv`.
- **External CLIs:** the backend calls the `docker compose` CLI as a subprocess for stack actions, and the `trivy` CLI for CVE scans.
- **Frontend:** React 18, Vite 5, TypeScript, react-router 6, CodeMirror (YAML), xterm.js (console), lucide-react icons. Plain CSS in `frontend/src/styles.css`, no UI framework.
- **Packaging:** one Docker image (amd64 + arm64). FastAPI serves the API and the built frontend on port 8080.

## Layout

```text
backend/
  app/
    main.py            app setup, router mounting, SPA fallback, logging
    api/               one router per area (projects, containers, console, images,
                       volumes, scans, updates, jobs, logs, settings, users, auth, dashboard)
    core/              config (env), database, migrations (Alembic runner), security
                       (sessions, bcrypt), log_buffer (in-memory app log)
    models/            SQLAlchemy models
    schemas/           Pydantic API models
    services/          logic: docker_service, compose_service, repo_service, trivy_service,
                       registry_service, update_service, job_service, tasks, scheduler_service,
                       settings_service, notify_service
  migrations/versions/ Alembic revisions
  tests/               pytest
frontend/src/
  pages/               one file per route
  components/          shared UI (LogPanel, JobList, JobsIndicator, ContainerConsole, ...)
  hooks/               useJobs, useContainerStats
  api.ts, types.ts     typed API client and response types
sample-repo/           Compose stacks for local dev
Dockerfile             3-stage build (frontend, backend venv, runtime with docker/compose/trivy)
.github/workflows/     multi-arch build and push to ghcr.io
```

## Key behaviour

- **Project discovery** (`repo_service`): walks `DRYDOCK_REPO_PATH` and skips dot folders.
  - A project is any `docker-compose.y(a)ml` or `compose.y(a)ml`, plus any other `*.yml` or `*.yaml` with a top-level `services:` mapping. `*.override.*` files are skipped.
  - The project ID is a hash of the file path.
  - Containers are matched to a project by the `com.docker.compose.project.config_files` label: the exact path first, then a path ending in the same repo-relative path (host and container mount roots differ), then by project name.
- **Editing:** validate the YAML first, then back up to `/data/backups/<project-id>/`, then write. New stacks are created as `<repo>/<name>/docker-compose.yml`. The name must match `^[a-z0-9][a-z0-9_-]*$`.
- **Background jobs** (`job_service`, `tasks`): anything slow (scans, update checks, container update, project compose actions, image and volume prunes) returns a job with status 202. Command output goes in `Job.output`. The UI polls `/api/jobs`. `useJobs` re-attaches to active jobs when a page opens. `JobsIndicator` in the topbar shows them from any page.
- **Update checks** (`update_service`): two independent signals.
  - Digest: the same tag was rebuilt (`latest`, `stable`).
  - Newer tag: `registry_service` lists the registry's tags over the v2 API with an anonymous bearer token. Only tags of the same shape count (same prefix, same number of parts, same suffix), so prereleases and other variants are ignored. It reports the newest tag and the newest within the current major, and skips outlier majors (a jump of more than 3).
- **Live data:** logs use SSE (`/api/logs/...`). Container stats are polled every 5s. The console is a WebSocket (`/api/containers/{id}/exec`).
- **Auth:** signed session cookie (Starlette `SessionMiddleware`), users table with an `is_admin` flag. A bootstrap admin is created on first start.
  - Admin only: settings writes, users, app logs, console, unmasked env values.
  - The console WebSocket is outside the HTTP auth dependency. It checks the session and the `Origin` header itself. Keep that check: other apps on the same host are same-site, so the browser sends them the cookie too.
- **Database:** Alembic owns the schema. Startup upgrades to head and snapshots the database to `<data>/backups/db/` first (keeps 5). Never use `create_all`. See "Database migrations" below.
- **API:** REST under `/api`; every router except `auth` and `/api/health` requires a session. FastAPI docs at `/docs` list all routes.

## Development

Run from the repo root. VS Code: the compound launch config **"Full stack (backend + frontend)"** starts both with the debugger.

```powershell
# backend (port 8080)
cd backend
uv sync --extra dev
$env:DRYDOCK_REPO_PATH = "$PWD\..\sample-repo"; $env:DRYDOCK_DATA_PATH = "$PWD\.data"
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8080

# frontend (port 5173, proxies /api including WebSockets)
cd frontend; npm install; npm run dev
```

Login: `admin` / `admin` (dev default).

Checks before you finish a change:

```powershell
cd backend;  uv run ruff check app tests;  .venv\Scripts\python.exe -m pytest -q
cd frontend; npx tsc --noEmit -p .;  npm run build
```

Windows gotchas:
- `uv run uvicorn` or `uv run pytest` can fail with `Failed to canonicalize script path`, because the venv launchers are stale. Use `python -m ...`, or run `uv sync --reinstall`.
- `uvicorn --reload` sometimes hangs after an edit: the old process keeps serving. Restart it.
- Trivy is not installed locally (`winget install AquaSecurity.Trivy`), so scans fail in dev without it. The Docker image includes it.

## Database migrations

After changing a model in `backend/app/models/`, generate a revision and review it before committing:

```powershell
cd backend
$env:DRYDOCK_DATA_PATH = "$PWD\.data"
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "add foo to scans"
uv run alembic check       # fails if models and migrations differ
```

- Never edit a released revision. Add a new one.
- SQLite cannot alter most things in place, so autogenerate emits `batch_alter_table` blocks that rebuild the table. Keep them.
- Autogenerate misses renames and data changes. Write those by hand.
- A new `NOT NULL` column on an existing table needs a `server_default` or a backfill.
- `tests/test_migrations.py` checks a fresh upgrade matches the models and a downgrade to base works.

## Conventions

- Match the surrounding style. Comments explain why, not what. Ruff with line length 100.
- Every route that does Docker work maps `docker_service.DockerUnavailable` to an HTTP error. Never let docker-py exceptions escape.
- Anything slower than about 1s goes through `job_service`, not a blocking request.
- Shell out with argument lists only (`subprocess.run([...])`), never `shell=True`.
- Frontend: all calls go through `api.ts`, and all types live in `types.ts`. Load heavy components lazily (`YamlEditor`, `ContainerConsole`).
- Docs (`README.md`, this file) use plain, short sentences.

## Principles

- Simple over complete. Local-first. Pi-friendly: few dependencies, cheap polling.
- Safe defaults: back up before writing, confirm destructive actions, never auto-update.
- Mounting the Docker socket gives root on the host. LAN, VPN or Tailscale only, behind auth.

## Non-goals

Kubernetes, Swarm, multi-host, RBAC beyond admin/user, plugins, an auto-update engine, registry mirroring, public internet exposure.

## Known gaps

- Root-level Compose files share the Compose project name of the repo folder (no `-p` is passed). This can clash with stacks started from the host.
- The Trivy DB cache is not on `/data`, so it is downloaded again after the container is recreated.
- No registry credentials: private registries fail both update checks.
- YAML backups cannot be browsed or restored from the UI yet.
- `todo.txt`: multilanguage UI.
