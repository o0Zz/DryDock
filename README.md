# HarborGuard

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
$env:HARBORGUARD_REPO_PATH = "C:\dev\HarborGuard\sample-repo"
$env:HARBORGUARD_DATA_PATH = "$PWD\.data"

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

## Docker image

HarborGuard ships as a single image that serves both the FastAPI backend and the built React frontend on port 8080. The image includes the `docker` + `docker compose` CLI and the [Trivy](https://github.com/aquasecurity/trivy) scanner.

Build & run:

```powershell
docker build -t harborguard/harborguard:latest .
docker compose up -d
```

For a Raspberry Pi (arm64), do a multi-arch build:

```bash
docker buildx build --platform linux/amd64,linux/arm64 -t harborguard/harborguard:latest --load .
```

Mounts (see `docker-compose.yml`):

| Host                              | Container | Purpose                                 |
| --------------------------------- | --------- | --------------------------------------- |
| `/var/run/docker.sock`            | same      | Control the Docker daemon               |
| `/path/to/your/compose-repo`      | `/repo`   | Scanned for Compose projects            |
| `harborguard_data` (named volume)    | `/data`   | SQLite DB + YAML backups                |

Once running, open <http://localhost:8080>.

## Configuration

All settings are read from environment variables prefixed `HARBORGUARD_`:

| Variable                 | Default   | Purpose                              |
| ------------------------ | --------- | ------------------------------------ |
| `HARBORGUARD_REPO_PATH`     | `/repo`   | Root folder scanned for Compose files |
| `HARBORGUARD_DATA_PATH`     | `/data`   | SQLite DB + backups live here         |
| `HARBORGUARD_HOST`          | `0.0.0.0` | uvicorn bind address                  |
| `HARBORGUARD_PORT`          | `8080`    | uvicorn port                          |
| `HARBORGUARD_CORS_ORIGINS`  | `["http://localhost:5173"]` | CORS allow list         |

## Status

Currently implemented:

- [x] Project discovery from mounted repo
- [x] Project list UI
- [ ] Compose YAML editor
- [ ] Stack actions (up/down/pull/restart)
- [ ] Container list
- [ ] Live logs
- [ ] Trivy CVE scanning
- [ ] Update checks
- [ ] Authentication
- [ ] Single-image Docker packaging
