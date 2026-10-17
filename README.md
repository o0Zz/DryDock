# DryDock

Lightweight self-hosted Docker Compose management UI for homelabs and Raspberry Pi setups. See `CLAUDE.md` for the full project brief.

## Repo layout

```
backend/       FastAPI + docker-py + Trivy backend
frontend/      React + Vite + TypeScript UI
sample-repo/   Example Compose stacks for local testing
```

## Development

The backend and frontend run as two separate dev servers. The Vite dev server proxies `/api/*` to the backend on port 8080.

### Backend

Uses [uv](https://docs.astral.sh/uv/) for dependency + venv management.

```powershell
cd backend
uv sync --extra dev

# Point at the sample repo (Windows-friendly absolute path):
$env:DRYDOCK_REPO_PATH = "C:\dev\DryDock\sample-repo"
$env:DRYDOCK_DATA_PATH = "$PWD\.data"

uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
```

Check it's alive: <http://localhost:8080/api/health>

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

Open <http://localhost:5173>. Requests to `/api/*` are proxied to the backend.

## Features

### Compose projects

`/repo` is scanned recursively for `docker-compose.yml`, `docker-compose.yaml`, `compose.yml` and `compose.yaml`. Each file becomes a project with its services, its containers (matched via Docker's Compose labels) and an editor.

The editor validates YAML and basic Compose structure before writing, and always copies the previous file to `/data/backups/<project-id>/` first. `up`, `down`, `pull`, `restart` and `stop` shell out to `docker compose`; `down` asks for confirmation.

### Logs

Server-Sent Events, for a single container (`/api/logs/container/{id}`) or a whole stack (`/api/logs/project/{id}`, backed by `docker compose logs -f`).

### CVE scanning

Trivy scans run as **background jobs** — a scan of a busy image takes minutes, which is far too long to hold an HTTP request open on a Pi. `POST /api/scans/*` returns a job immediately and the UI polls `/api/jobs/{id}` for progress.

Three scan modes: one image, every image used by a running container, and every image referenced by a Compose file. Results are stored per image with severity counts plus the individual findings (CVE id, package, installed/fixed version, link), capped at the 500 most severe per scan.

### Update checks

`POST /api/updates/check` compares each image's local `RepoDigest` against the digest its registry currently serves. This is a manifest lookup only — nothing is downloaded — so it is cheap enough to run across every image. Images built locally have no registry digest and are reported as such rather than as "up to date".

### Schedules and notifications

Scans and update checks can run on an interval (APScheduler), configured on the Settings page. After a *scheduled* run, DryDock can POST a JSON summary to a webhook:

```json
{
  "source": "drydock",
  "event": "scan.critical",
  "images": [{ "image": "nginx:1.25", "critical": 2, "high": 7, "fixable": 6 }],
  "summary": "4 image(s) scanned, 2 critical, 11 high"
}
```

The other event is `update.available`, whose `images` is a list of image names. Manual runs never notify.

## Docker image

DryDock ships as a single image that serves both the FastAPI backend and the built React frontend on port 8080. The image includes the `docker` + `docker compose` CLI and the [Trivy](https://github.com/aquasecurity/trivy) scanner.

Build & run:

```powershell
docker build -t drydock/drydock:latest .
docker compose up -d
```

For a Raspberry Pi (arm64), do a multi-arch build:

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t drydock/drydock:latest --load .
```

Mounts (see `docker-compose.yml`):

| Host                              | Container | Purpose                                 |
| --------------------------------- | --------- | --------------------------------------- |
| `/var/run/docker.sock`            | same      | Control the Docker daemon               |
| `/path/to/your/compose-repo`      | `/repo`   | Scanned for Compose projects            |
| `drydock_data` (named volume)     | `/data`   | SQLite DB, YAML backups, session key    |

Once running, open <http://localhost:8080>.

## Configuration

Deployment settings are environment variables prefixed `DRYDOCK_`. Anything you can change at runtime (schedules, notifications) lives on the Settings page instead, stored in the database.

| Variable                     | Default                     | Purpose                                        |
| ---------------------------- | --------------------------- | ---------------------------------------------- |
| `DRYDOCK_REPO_PATH`          | `/repo`                     | Root folder scanned for Compose files          |
| `DRYDOCK_DATA_PATH`          | `/data`                     | SQLite DB, backups and session key live here   |
| `DRYDOCK_HOST`               | `0.0.0.0`                   | uvicorn bind address                           |
| `DRYDOCK_PORT`               | `8080`                      | uvicorn port                                   |
| `DRYDOCK_CORS_ORIGINS`       | `["http://localhost:5173"]` | CORS allow list                                |
| `DRYDOCK_ROOT_PATH`          | *(empty)*                   | Set when a proxy serves the app under a subpath |
| `DRYDOCK_SECRET_KEY`         | *(generated)*               | Session signing key; persisted to `/data` if unset |
| `DRYDOCK_SESSION_HTTPS_ONLY` | `false`                     | Set true behind a TLS-terminating proxy        |
| `DRYDOCK_SESSION_MAX_AGE`    | `1209600`                   | Session lifetime in seconds (14 days)          |
| `DRYDOCK_ADMIN_USERNAME`     | `admin`                     | Bootstrap admin, created only on first start   |
| `DRYDOCK_ADMIN_PASSWORD`     | `admin`                     | **Change this immediately after first login**  |

### Behind a reverse proxy

The container runs uvicorn with `--proxy-headers`, so `X-Forwarded-Proto` / `X-Forwarded-For` are honoured. For a subpath deployment also set `DRYDOCK_ROOT_PATH=/drydock`, and set `DRYDOCK_SESSION_HTTPS_ONLY=true` when TLS terminates at the proxy.

## API

```
GET    /api/health
POST   /api/auth/login | /api/auth/logout | /api/auth/password
GET    /api/auth/me

GET    /api/dashboard

GET    /api/projects                       list + their containers
GET    /api/projects/{id}
GET    /api/projects/{id}/compose
PUT    /api/projects/{id}/compose          validates, backs up, writes
POST   /api/projects/{id}/{up|down|pull|restart|stop}

GET    /api/containers | /api/containers/{id}
POST   /api/containers/{id}/{start|stop|restart}

GET    /api/logs/container/{id}            SSE
GET    /api/logs/project/{id}              SSE

GET    /api/scans                          latest per image (?image= for history)
GET    /api/scans/{id}                     counts + individual findings
POST   /api/scans/image | /running | /compose      -> 202 job

GET    /api/updates                        latest per image (?image= for history)
POST   /api/updates/check                  -> 202 job

GET    /api/jobs | /api/jobs/{id}

GET    /api/settings
PUT    /api/settings                       admin only

GET    /api/volumes | /api/volumes/{name}
POST   /api/volumes | /api/volumes/prune
DELETE /api/volumes/{name}

GET    /api/users                          admin only
POST   /api/users | PATCH /api/users/{id} | DELETE /api/users/{id}
```

## Status

Implemented:

- [x] Project discovery from mounted repo
- [x] Project list + stack status
- [x] Compose YAML editor (CodeMirror, validated, backed up)
- [x] Stack actions (up/down/pull/restart/stop)
- [x] Container list with ports, restart policy and created time
- [x] Live logs for a container and for a whole stack
- [x] Trivy CVE scanning: one image, all running, all Compose images
- [x] Per-CVE detail with links and fixed versions
- [x] Update checks via registry digest comparison
- [x] Dashboard CVE and update summary
- [x] Background job queue with progress
- [x] Scheduled scans and update checks, with webhook notifications
- [x] Authentication (users, sessions, admin role)
- [x] Settings page
- [x] Volume management
- [x] Single-image Docker packaging (amd64 + arm64)

Not done yet:

- [ ] Automated tests (pytest is wired up, no suite written)
- [ ] CPU/RAM usage per container
- [ ] Browsing and restoring YAML backups from the UI
- [ ] Registry credentials for update checks against private registries
