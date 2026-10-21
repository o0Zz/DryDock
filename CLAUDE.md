# DryDock

A small, self-hosted web UI for Docker Compose stacks on a homelab or Raspberry Pi. It is a focused alternative to Portainer. A mounted folder of Compose files is the source of truth. DryDock lists the stacks, edits them, runs them, scans their images for CVEs and checks for image updates.

The repo folder is named `HarborGuard`, an earlier name. The product, the env prefix (`DRYDOCK_`), the package and the image are all **DryDock**.

`README.md` is the short, user-facing page (features, quick start, config). Contributor detail lives here. Keep both in sync when behaviour changes.

## Stack

- **Backend:** Python 3.11, FastAPI, SQLAlchemy 2 (sync) on SQLite, Alembic, docker-py, APScheduler, httpx. Managed with `uv`.
- **External CLIs:** the backend calls the `docker compose` CLI as a subprocess for stack actions, and the `trivy` CLI for CVE scans.
- **Frontend:** React 18, Vite 5, TypeScript, react-router 6, CodeMirror (YAML), xterm.js (console), lucide-react icons. Plain CSS in `frontend/src/styles.css`, no UI framework.
- **Packaging:** one Docker image (amd64 + arm64). FastAPI serves the API and the built frontend on port 8080.
- **Version:** `release/X.Y.Z` gives `X.Y.Z+<commit count>` (`release/X.Y` counts as `X.Y.0`), a `vX.Y.Z` tag gives `X.Y.Z`, any other branch gives `0.0.0-<branch>+<commit count>`. Docker tags do not allow `+`, so the release image tag uses `-` (`1.1.1-445`). CI passes it as `APP_VERSION`. A local `docker compose build` computes it from `.git` in the Dockerfile's `version` stage. A git URL context only has a `.git` with the build arg `BUILDKIT_CONTEXT_KEEP_GIT_DIR=1` (an `ARG` in the Dockerfile does not work). That clone is shallow with a detached HEAD, so the stage fetches the commit history (`--filter=tree:0`) and takes the branch from `refs/heads`. The image stores it in `/app/VERSION`. A backend run from a checkout reports `0.0.0-dev`, and the Vite frontend computes its own.

## Layout

```text
backend/
  app/
    main.py            app setup, router mounting, SPA fallback, logging
    api/               one router per area (projects, containers, console, images,
                       volumes, networks, scans, updates, jobs, logs, settings, users, auth, dashboard, git, ai)
    core/              config (env), database, migrations (Alembic runner), security
                       (sessions, bcrypt), log_buffer (in-memory app log)
    models/            SQLAlchemy models
    schemas/           Pydantic API models
    services/          logic: docker_service, compose_service, repo_service, trivy_service,
                       registry_service, update_service, job_service, tasks, scheduler_service,
                       settings_service, notify_service, history_service, host_service,
                       volume_files_service, host_updates_service, fail2ban_service,
                       stats_history_service, git_service, git_auth_service, repo_git_service,
                       ai_service
  migrations/versions/ Alembic revisions
  tests/               pytest
frontend/src/
  pages/               one file per route
  components/          shared UI (LogPanel, JobList, JobsIndicator, ContainerConsole,
                       ComposeAssistant, AiSettings, ...)
  hooks/               useJobs, useContainerStats, useSort (click-to-sort tables with SortHeader)
  api.ts, types.ts     typed API client and response types
  i18n.tsx, i18n/fr/   translations: English text is the key, one JSON file per UI area
docs/                  user docs (troubleshooting.md)
sample-repo/           Compose stacks for local dev
Dockerfile             3-stage build (frontend, backend venv, runtime with docker/compose/buildx/trivy/git)
.github/workflows/     multi-arch build and push to ghcr.io
```

## Key behaviour

- **Project discovery** (`repo_service`): walks `DRYDOCK_REPO_PATH` and skips dot folders.
  - A project is any `docker-compose.y(a)ml` or `compose.y(a)ml`, plus any other `*.yml` or `*.yaml` with a top-level `services:` mapping. `*.override.*` files are skipped.
  - The project ID is a hash of the file path.
  - Containers are matched to a project by the `com.docker.compose.project.config_files` label: the exact path first, then a path ending in the same repo-relative path (host and container mount roots differ), then by project name.
- **Host paths** (`host_path_service`): the Docker daemon resolves bind-mount paths on the host, but Compose builds them from where DryDock sees the file (`/repo/...`). At startup DryDock reads the host source of its own `/repo` mount and creates a symlink at that host path pointing to `/repo`. Compose then runs through that path, so `./file` mounts resolve on the host. `DRYDOCK_REPO_HOST_PATH` overrides detection.
- **Compose commands** (`compose_service`): DryDock passes `-f`, which turns off Compose's own override merge. So it adds `-f <stem>.override.y(a)ml` itself when that file sits next to the Compose file.
  - `-p`: a canonical file (`docker-compose.yml` and friends) keeps Compose's default, the folder name. A freely named file (`media.yml`) gets its own name, so files in one folder (the repo root included) do not share a project. A running stack keeps the project name of its containers, so `down` still finds them. See `repo_service.compose_project_name`.
- **Editing:** validate the YAML first, then back up to `/data/backups/<project-id>/`, then write. New stacks are created as `<repo>/<name>/docker-compose.yml`. The name must match `^[a-z0-9][a-z0-9_-]*$`.
  - The stack page flags a Compose file newer than its newest container: the edit was likely not deployed. `up` only recreates changed services, so the newest container is the one to compare.
  - The `.env` next to the Compose file gets the same flow (admin only). `compose_service._validate_env` checks the dotenv syntax Compose accepts: `KEY=value`, `export KEY=value`, `KEY: value`, a bare `KEY`, and quoted values that span lines. Stacks in one folder share one `.env`.
- **Stack management** (`stack_service`, jobs of kind `stack_change`): delete, rename, duplicate. A stack owns its folder when the folder is not the repo root and holds no other stack (nested ones count). Then the whole folder is the stack: delete archives it to `/data/backups/<project-id>/<stamp>-stack.tar.gz` and removes it, rename moves it, duplicate copies it. Otherwise only the Compose file and its override are backed up, moved or copied, and the rest of the folder (`.env` included) stays.
  - The new name is the new Compose project name: a canonical file keeps its name in the renamed folder, any other file is renamed `<name>.yml`. Routes check the name (free, no existing path) before queueing, and return the stack's new ID.
  - Delete and rename run `down` first when the stack has containers (delete also with `-v` on request). A rename leaves the stack down: its named volumes keep the old project name.
- **Background jobs** (`job_service`, `tasks`): anything slow (scans, update checks, container update, project compose actions, image and volume prunes) returns a job with status 202. Command output goes in `Job.output`. The UI polls `/api/jobs`. `useJobs` re-attaches to active jobs when a page opens. `JobsIndicator` in the topbar shows them from any page. Jobs run in this process's threads, so startup marks any job still pending or running as failed (`job_service.fail_interrupted`): a restart kills it.
  - Compose commands of a job (stack actions, container update, `down` before a delete or rename) run in a helper container (`compose_service._run_in_helper`): a detached copy of DryDock with its image, mounts (`volumes_from`) and user, labelled `drydock.job=<job id>`. The image is the container's own, or what its tag points to now: with the containerd image store, rebuilding the tag makes the old image ID unresolvable while DryDock still runs on it (`docker_service.container_image`). The helper is created and started, never `run`, so docker-py never tries to pull an image ID. Compose stops a container before it creates the new one, so a Compose process inside DryDock would die when it updates DryDock itself, and the stack would stay down. The job follows the helper's logs. On shutdown it lets go (`job_service.Interrupted`) and the job stays active; startup resumes it from the helper (`tasks.resume_compose_jobs`). Steps after the Compose run (the update re-check) are skipped then.
  - The helper does not have the host-path symlink, so it mounts the repo's host path at that same path. Outside Docker (dev) and outside a job, Compose runs as a plain subprocess.
- **Update checks** (`update_service`): two independent signals for registry images, a third for git builds.
  - Digest: the same tag was rebuilt (`latest`, `stable`).
  - Running version: `Container.image_version` comes from the `org.opencontainers.image.version` label (container labels include image labels, so no extra inspect). It is dropped when `ref.name` names another image, such as a version inherited from an ubuntu base. Many official Docker Hub images do not set it.
  - Newer tag: `registry_service` lists the registry's tags over the v2 API with a bearer token (anonymous, or logged in with the stored credentials). Only tags of the same shape count (same prefix, same number of parts, same suffix), so prereleases and other variants are ignored. It reports the newest tag and the newest within the current major, and skips outlier majors (a jump of more than 3).
  - Git build (`git_service`): a service whose `build:` is a git URL (`https://…/app.git#ref`) is checked by commit, not digest. `git_service.remote_commit` reads the refs over git smart HTTP (`/info/refs`), like `git ls-remote`, with no git binary and no clone. The `UpdateCheck` row gets `git_source`, and its digests hold commits: the one built and the latest. The built commit carries over from the previous git row. A container update or a project "Pull & build" stores the current commit as built. Without a previous row, the first check takes the current commit as the baseline. Only http(s). A private repo uses the git login for its host. The image name of a service without `image:` comes from its containers (`tasks.git_images`).
  - Container update runs `pull --ignore-buildable`, `build --pull`, then `up -d --no-deps` on the service. Each step is a no-op for the other kind of service.
- **Git logins** (`git_auth_service`, admin only): one login per host, in `<data>/git/credentials` (git's credential store format, mode 600), plus a file per host with its `Authorization` header value.
  - Update check: `git_service.list_refs` sends it as basic auth.
  - Build: BuildKit clones a git context with the build secret `GIT_AUTH_HEADER.<host>`. `compose_service._command` adds one more `-f`: a generated `<data>/git/compose/<project-id>.yml` that declares that secret for each service built from a host with a login. It is an `environment:` secret (`DRYDOCK_GIT_AUTH_<n>`): bake refuses a `file:` secret outside the project without `--allow fs.read`, which Compose 5.6 does not pass. A plain run gets the variables in its env. The helper container's script sets them from the header files in `/data` first, so its config holds no token. Compose's config hash ignores `build:`, so `up` does not recreate anything for it.
  - Saving with a repo URL checks it with `/info/refs` first. A bare host is stored unchecked.
  - Registry and git logins share the UI (`LoginTable`): every field of a stored row is editable. The API never returns a password, so `PUT` with an empty one keeps the stored one, and a new host or registry moves the login.
- **Repo git** (`repo_git_service`, jobs of kind `repo_git`, admin only): status, commit, push, pull of the repo folder. The `.git` may be in a parent of `DRYDOCK_REPO_PATH` (mount the repo root, point the path at the sub-folder; `mount_source` maps a path inside a mount for the host-path alias).
  - `-- .` from the repo folder: the change list and the commit cover only that folder, whatever else is staged.
  - git runs as the owner of `.git` (`subprocess.run(user=...)`), so objects and pulled files stay theirs and git's ownership check passes. `HOME` moves to the temp dir, because root's home is unreadable for that user.
  - Push and pull get the login as `http.<host>.extraheader` through `GIT_CONFIG_*` env vars: out of the process list, and no credential file the owner cannot read. https only. Pull is `--ff-only`.
  - Without `user.name` in the repo config, the author is the DryDock user (`<name>@drydock.local`). The host's global git config is not visible.
- **AI assistant** (`ai_service`, `/api/ai`): a chat beside the Compose editor (`ComposeAssistant`). It proposes a whole new file; the UI shows a line diff (`lineDiff.ts`) and "Apply" puts it in the editor. Saving stays the normal validate, back up, write flow.
  - Providers: OpenAI (`/chat/completions`, editable base URL for compatible servers), Anthropic (`/v1/messages`), GitHub Copilot. Plain httpx, no SDK. One is active.
  - Keys live in `<data>/ai/config.json` (mode 600). The API never returns them; an empty key on `PUT` keeps the stored one. Config is admin only, the chat is open to anyone who can edit a Compose file.
  - Copilot has no API key. The admin signs in with GitHub's device flow, with Copilot's own OAuth client ID (Copilot only gives tokens to apps it knows). DryDock stores the GitHub token and trades it for a short-lived Copilot token (`copilot_internal/v2/token`, cached until a minute before expiry). That endpoint is not a public API and may change.
  - Each request sends the system prompt, the last 20 messages and the current editor content in the last user message. Earlier proposals are sent without their file. The model ends a change with one `yaml` block; `edit_compose` takes the last one and runs `compose_service.validate_yaml` on it. An invalid file still comes back, with `error` set.
  - The chat call blocks (up to 180s) instead of being a job: the user waits for the answer. Provider failures map to 502, a missing setup to 400.
  - Only the Compose file is sent, never the `.env`.
- **Networks** (`docker_service`): a network's inspect only lists running containers, and `docker network prune` goes by that, so it would remove the networks of stopped stacks. DryDock builds usage from every container's `NetworkSettings.Networks`, keyed by network name (a container that never started has no `NetworkID` yet). Remove and prune refuse used networks and Docker's own (`bridge`, `host`, `none`); prune is a job that removes the free ones one by one.
- **Live data:** logs use SSE (`/api/logs/...`). Container stats are polled every 5s. Each poll also feeds `stats_history_service`, an in-memory ring buffer (60 samples, about 5 min, lost on restart) behind the CPU and memory sparklines. It has no sampler of its own, so it only fills while a page polls. The console is a WebSocket (`/api/containers/{id}/exec`).
- **Dashboard:** `/api/dashboard` returns counts and the "needs attention" lists in one call. CVE and update counts only include tracked images (running or named in a Compose file), so replaced tags stop counting. Host facts come from `docker info`.
  - Host load (`/api/dashboard/host`, polled every 5s) comes from `host_service`. It reads `/proc` and `/sys/class/thermal`. These are not namespaced, so inside the container they describe the host. Each value is `null` where missing (Windows dev, VMs without a sensor).
- **Volume files** (`volume_files_service`): volume data lives under the Docker root on the host, which DryDock cannot see. Each request uses a throwaway helper container with the volume mounted read-only at `/volume` and no network.
  - Listing runs `find <dir>/ -mindepth 1 -maxdepth 1 -exec stat -c '%f %s %Y %n' {} +`. It works with GNU and busybox tools. Folders over 2000 entries are cut and flagged `truncated`.
  - Download creates the helper without starting it and streams the file out with `get_archive` (`docker cp`). Only regular files download. The helper is removed when the stream ends.
  - The helper uses DryDock's own image, so nothing is pulled. Outside a container (dev) it falls back to `DRYDOCK_HELPER_IMAGE`, pulled on first use.
- **Host helpers** (`docker_service.run_on_host`, `read_host_file`): same idea as volume files, for host paths. They mount with a `Mount`, not a `volumes` bind, so a missing source fails instead of creating an empty folder on the host.
  - Host updates (`host_updates_service`): a helper mounts `/` read-only at `/host` and runs `chroot /host sh -c SCRIPT`. The host's own `apt list --upgradable` reads the host's package state. Packages from a `*-security` suite count as security updates. "Reboot required" is `/var/run/reboot-required`, or the running kernel's `/lib/modules` folder being gone. It runs with the image update check schedule and keeps the last 30 rows. No apt on the host gives `supported = false`. `auto_upgrades` is true when `unattended-upgrade` exists and `APT::Periodic::Unattended-Upgrade` is above 0. DryDock never upgrades the host: the page shows the commands to run there.
  - The list is only as fresh as the host's last `apt update`. The page flags lists older than 7 days.
  - fail2ban (`fail2ban_service`, admin only): `read_host_file` copies `DRYDOCK_FAIL2BAN_DB` out, and `sqlite3` opens it in memory (`deserialize`). Active bans come from `bips` (0.11+), history from `bans`. The history only goes back fail2ban's `dbpurgeage` (1 day by default).
- **Auth:** signed session cookie (Starlette `SessionMiddleware`), users table with an `is_admin` flag. A bootstrap admin is created on first start.
  - Default password: an account on `admin` (`DEFAULT_ADMIN_PASSWORD`) gets `must_change_password`, at bootstrap or at login (older installs). `get_current_user` then answers 403 everywhere, tokens included. Only `/api/auth/me`, `/password` and `/logout` work, through `get_authenticated_user`. The console WebSocket refuses too. The UI shows only `ChangeDefaultPassword` until the change.
  - API tokens (`api_tokens` table, `/api/tokens`): `get_current_user` also accepts `Authorization: Bearer ddt_...`. Only a SHA-256 of the token is stored, and the token acts as its user. `last_used_at` is written at most once a minute.
  - Admin only: settings writes, users, app logs, console, unmasked env values, `.env` files, volume files, registry credentials, git logins and repo git, fail2ban, AI provider setup.
  - The console WebSocket is outside the HTTP auth dependency. It checks the session and the `Origin` header itself. Keep that check: other apps on the same host are same-site, so the browser sends them the cookie too.
- **Registry credentials** (`registry_auth_service`): stored in a standard Docker `config.json` at `<data>/docker/` (base64 `auths`, mode 600). `docker compose` and `trivy` get `DOCKER_CONFIG` pointing there (`subprocess_env()`), the digest check passes `auth_config` to the daemon, and the tag check logs in to the token endpoint. Saving a login first checks it with `docker login` on a throwaway client. Credential helpers (`credsStore`) are not supported.
- **Trivy** runs with `--cache-dir <data>/trivy-cache`, so its DB survives the container being recreated.
- **Database:** Alembic owns the schema. Startup upgrades to head and snapshots the database to `<data>/backups/db/` first (keeps 5). Never use `create_all`. See "Database migrations" below.
- **API:** REST under `/api`; every router except `auth` and `/api/health` requires a session or an API token. FastAPI docs at `/docs` list all routes.

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
cd frontend; npx tsc --noEmit -p .;  npm run i18n:check;  npm run build
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
- UI text goes through `t("English text", { vars })` from `useT()` (`i18n.tsx`). Text defined outside a component is marked `msg("...")` and passed to `t()` where shown; plain helpers use `translate()`. Add the French to `src/i18n/fr/<area>.json` (shared words in `common.json`). `npm run i18n:check` fails on a missing key or a placeholder mismatch. Keep whole sentences as one key; never translate API data or values used in logic.
- Layout: one breakpoint at 768px in `styles.css`. Below it the sidebar is a drawer (menu button in the topbar), tables scroll sideways, and panels become bottom sheets. New wide content must not push the page wider than the screen.
- Docs (`README.md`, this file) use plain, short sentences.

## Principles

- Simple over complete. Local-first. Pi-friendly: few dependencies, cheap polling.
- Safe defaults: back up before writing, confirm destructive actions, never auto-update.
- Mounting the Docker socket gives root on the host. LAN, VPN or Tailscale only, behind auth.

## Non-goals

Kubernetes, Swarm, multi-host, RBAC beyond admin/user, plugins, an auto-update engine, registry mirroring, public internet exposure.

## Known gaps

- Volume files are read-only: no upload, edit or delete.
- YAML backups cannot be browsed or restored from the UI yet.
- Server messages (API errors, job labels and output) are English only.
