# DryDock

DryDock is a lightweight, self-hosted web UI for Docker Compose stacks, made for homelabs and Raspberry Pi. You mount a folder of Compose files, and DryDock lets you run, edit, watch and secure them from your browser.

DryDock is designed to help you keep your containers secure over time:
- **Know your vulnerabilities:** Trivy scans your images and shows which CVEs have a fix.
- **Stay up to date:** DryDock finds newer images, including newer version tags for pinned images.
- **Get alerted:** scheduled scans and update checks can call a webhook when something needs attention.
- **Change safely:** Compose edits are validated and backed up first, and nothing updates automatically.
- **Control access:** login is required, and only admins can open a container shell or see secret values.

It runs as a single Docker image with a SQLite database. No cloud, no Kubernetes.

> **Security:** DryDock mounts the Docker socket, which gives it root on the host. Use it only on your LAN, a VPN or Tailscale. Never expose it to the internet.

## Quick start

```yaml
services:
  drydock:
    image: ghcr.io/<owner>/<repo>:latest
    container_name: drydock
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /home/pi/docker:/repo        # your Compose files
      - drydock_data:/data           # database and backups
    environment:
      - TZ=Europe/Paris

volumes:
  drydock_data:
```

1. Run `docker compose up -d`.
2. Open <http://localhost:8080>.
3. Log in with `admin` / `admin`, then change the password.

Works on `amd64` and `arm64` (Raspberry Pi 3, 4 and 5 with 64-bit OS).

## Features

- **Stacks:** every Compose file in your folder shows up as a project. Any `*.yml` file with a `services:` section counts. Start, stop, pull, restart or edit each one, or create a new stack.
- **Containers:** state, CPU and memory, ports, live logs, a detail page, and a shell in the browser.
- **Images:** see which images are in use, and remove or prune the rest.
- **CVE scans:** scan one image, all running images, or all images in your Compose files.
- **Updates:** finds rebuilt tags (`latest`, `stable`) and newer versions (`2025.10.4` → `2026.10.2`). For `postgres:16.2` you see both the newest `16.x` and the newest overall.
- **Background jobs:** scans, update checks, stack actions and prunes run in the background. The top bar shows progress from any page.
- **Schedules and alerts:** run scans and update checks on an interval, and send results to a webhook.
- **Users and volumes:** several users with an admin flag, and named volume management.
- **Logs page:** DryDock's own log, to see why a scan or a check failed.

## Configuration

Set these environment variables if you need to. Schedules and notifications are set on the Settings page.

| Variable                     | Default      | Purpose                                        |
| ---------------------------- | ------------ | ---------------------------------------------- |
| `DRYDOCK_REPO_PATH`          | `/repo`      | Folder with your Compose files                 |
| `DRYDOCK_DATA_PATH`          | `/data`      | Database, backups and session key              |
| `DRYDOCK_ADMIN_USERNAME`     | `admin`      | First admin, created on first start only       |
| `DRYDOCK_ADMIN_PASSWORD`     | `admin`      | First admin's password. Change it after login. |
| `DRYDOCK_ROOT_PATH`          | *(empty)*    | Set when served under a subpath, e.g. `/drydock` |
| `DRYDOCK_SESSION_HTTPS_ONLY` | `false`      | Set `true` behind an HTTPS proxy               |
| `DRYDOCK_SECRET_KEY`         | *(generated)* | Session signing key, saved in `/data` if not set |

Behind a reverse proxy, allow WebSocket upgrades so the container shell works. For nginx:

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

## Development

You need [uv](https://docs.astral.sh/uv/), Node.js and Docker. In VS Code, the launch config **"Full stack (backend + frontend)"** starts everything.

Backend, on port 8080:

```powershell
cd backend
uv sync --extra dev
$env:DRYDOCK_REPO_PATH = "$PWD\..\sample-repo"
$env:DRYDOCK_DATA_PATH = "$PWD\.data"
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8080
```

Frontend, on <http://localhost:5173>:

```powershell
cd frontend
npm install
npm run dev
```

CVE scans need [Trivy](https://github.com/aquasecurity/trivy) installed (`winget install AquaSecurity.Trivy` on Windows). The Docker image already includes it.

More detail for contributors (tests, database migrations, conventions) is in `CLAUDE.md`.

## Not done yet

- Browsing and restoring Compose file backups from the UI.
- Private registries (login for update checks and scans).
- Keeping Trivy's database cache across container rebuilds.
- A multilanguage UI.
