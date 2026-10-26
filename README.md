# DryDock

DryDock is a self-hosted control board for a home server or NAS that runs Docker: a Raspberry Pi, a mini PC, a NAS. One place shows what runs, which host name leads to which container, and what to fix to keep it all safe.

You mount a folder of Compose files. That folder stays the source of truth: DryDock lists the stacks, runs them, edits them, gives them host names and watches them.

DryDock does three jobs:

- **Run:** stacks, containers, images, volumes and networks. Start, stop, edit, update, read the logs, open a shell.
- **Expose:** give a service a host name (`jellyfin.example.org`) with HTTPS, private or public. The **Proxy** page lists every host name with the stack and the service behind it, its port, who can reach it, and whether it runs. Traefik, SWAG or Caddy carries the traffic; your Compose files only carry neutral `expose.*` labels, so you can switch proxy without touching them.
- **Secure:** built in, not an add-on.
  - **Vulnerabilities:** Trivy scans your images and shows which CVEs have a fix.
  - **Updates:** newer images and newer version tags, rebuilt git sources, and pending OS updates on the host, with security updates and "reboot required" flagged.
  - **Intrusions:** fail2ban jails on the proxy's access log (failed logins, scanners, bad bots), tested and applied from the UI. Bans and the log lines behind them show on the **Host** page.
  - **Known bad IPs:** a daily blocklist (FireHOL level1 by default) dropped by the host's firewall before it reaches any container. Private ranges and your allowlist are never blocked.
  - **Exposure:** private services only answer your LAN, your public IP and trusted IPs. Every route is HTTPS with HSTS. One wildcard certificate keeps your service names out of public certificate logs.
  - **Safe changes:** Compose edits are validated and backed up first. Nothing updates on its own.
  - **Access:** login is required. Only admins open a container shell, see secret values, edit `.env` files or read volume files.
  - **Alerts:** scheduled scans and update checks call a webhook when something needs attention.

The dashboard puts it together: running containers, open CVEs, updates, what needs attention, and host CPU, memory and temperature.

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
3. Log in with `admin` / `admin`. DryDock asks for a new password before anything else.

Works on `amd64` and `arm64` (Raspberry Pi 3, 4 and 5 with 64-bit OS).

To build from source instead, replace `image:` with a git URL. The build reads the version from the repo's `.git`, which Docker drops from a git URL unless you keep it:

```yaml
    build:
      context: https://github.com/<owner>/<repo>.git#main
      args:
        BUILDKIT_CONTEXT_KEEP_GIT_DIR: 1
```

## Features

### Run

- **Stacks:** every Compose file in your folder shows up as a project. Any `*.yml` file with a `services:` section counts. Start, stop, pull & build, reload or edit each one and its `.env`. **Pull & build** downloads newer images and rebuilds services that have a `build:` section. **Reload** stops the stack and runs `up`, so file changes apply. Create, rename, duplicate or delete a stack; a delete backs the stack up first. A `*.override.yml` next to a Compose file is merged in, like `docker compose up` does.
- **Containers:** start, stop, restart, pause, kill or rename. State, uptime, health check, restart count, CPU and memory with a 5-minute sparkline, ports, live logs, a detail page, and a shell in the browser.
- **Images:** see which images are in use, and remove or prune the rest.
- **Volumes:** named volume management. Admins can browse the files in a volume (read-only) and download them.
- **Networks:** driver, subnet and attached containers of every network. Remove one, or prune the custom networks no container uses. Networks of stopped stacks are kept, unlike `docker network prune`.
- **Background jobs:** scans, update checks, stack actions and prunes run in the background. The top bar shows progress from any page. Compose commands run in a short-lived helper container, so DryDock can update its own stack and come back.

### Expose

- **Host names:** give a service a host name (`jellyfin.example.org`) with HTTPS, private (an IP allowlist) or public. The **Expose** panel beside the Compose editor writes neutral `expose.*` labels that name no proxy.
- **Proxy page:** every host name in your Compose files, with its stack, service, container port, visibility and state, plus the health of the proxy and its sync. A host name already used by another stack is refused.
- **Your choice of proxy:** stack templates for Traefik, SWAG (nginx) or Caddy, each with a wildcard certificate. The labels work with all three. See [Reverse proxy](#reverse-proxy).

### Secure

- **CVE scans:** scan one image, all running images, or all images in your Compose files.
- **Image updates:** finds rebuilt tags (`latest`, `stable`) and newer versions (`2025.10.4` → `2026.10.2`). A service built from a git URL (`build: https://github.com/me/app.git#main`) shows an update when its ref gets a new commit, and Update rebuilds it. For `postgres:16.2` you see both the newest `16.x` and the newest overall. For a floating tag like `stable`, the containers list shows the version the image declares (`org.opencontainers.image.version` label), when it has one.
- **Host updates:** pending OS package updates on the host (Debian, Ubuntu, Raspberry Pi OS), with security updates and "reboot required" flagged on the dashboard. They are checked on the update check schedule, read-only: DryDock never installs anything. The page gives the command to run on the host, and says when automatic security updates (`unattended-upgrades`) are off.
- **fail2ban:** admins see the host's jails, active bans, the log lines behind each ban, and the user names tried on SSH. They also edit the jails that protect the reverse proxy (failed logins, refused requests, scanners, bad bots, or a custom regex), test a rule on the access log before saving, and apply it: DryDock writes its own jail file on the host and reloads fail2ban. Bans block the proxy's forwarded traffic, not only the host's own ports. No unban yet.
- **IP blocklist:** admins turn on a list of known bad IPs (FireHOL level1, or their own list URLs). DryDock downloads it every 24 hours and at startup, drops private ranges, and loads it in its own nftables table on the host (`inet drydock_blocklist`). The page shows the ranges loaded, the packets dropped, and checks whether an IP is blocked. The host needs `nft` (nftables).
- **Schedules and alerts:** run scans and update checks on an interval, and send results to a webhook.
- **Users and API tokens:** several users with an admin flag. Each user can create tokens on the Settings page for scripts and CI, e.g. `curl -H "Authorization: Bearer ddt_..." http://drydock:8080/api/containers`. A token has the rights of its user.

### Tools

- **Private registries:** admins save a login per registry (Docker Hub, GHCR, your own) on the Settings page. Update checks, pulls and scans use it. DryDock checks the login with the registry before it saves it.
- **Git logins:** admins save a login per git host (GitHub, Gitea, your own) on the Settings page. Builds from a private git URL and their update checks use it, with no token in your Compose files. Given a repo URL, DryDock checks the login before it saves it.
- **Git for the repo folder:** when your Compose folder is in a git repo, the Projects page lists the changes and has **Commit & push** and **Pull** (fast-forward only), for admins. See [Git](#git).
- **AI assistant:** a chat beside the Compose editor. Ask for a change ("add a healthcheck to web"), see the diff, apply it to the editor, then save as usual. Nothing is saved for you. Admins pick the provider on the Settings page: OpenAI (or any OpenAI-compatible server, such as Ollama), Anthropic with an API key, or GitHub Copilot with a GitHub sign-in. Only the Compose file is sent, never the `.env`.
- **English and French:** pick the language in the top bar; it defaults to your browser's. Works on a phone too: the menu folds into a drawer.
- **Logs page:** DryDock's own log, to see why a scan or a check failed.

## Configuration

Set these environment variables if you need to. Schedules and notifications are set on the Settings page.

| Variable                     | Default      | Purpose                                        |
| ---------------------------- | ------------ | ---------------------------------------------- |
| `DRYDOCK_REPO_PATH`          | `/repo`      | Folder with your Compose files                 |
| `DRYDOCK_REPO_HOST_PATH`     | *(detected)* | Host path of the repo. Only set it if detection fails (see Troubleshooting) |
| `DRYDOCK_DATA_PATH`          | `/data`      | Database, backups and session key              |
| `DRYDOCK_ADMIN_USERNAME`     | `admin`      | First admin, created on first start only       |
| `DRYDOCK_ADMIN_PASSWORD`     | `admin`      | First admin's password. `admin` must be changed at first login. |
| `DRYDOCK_ROOT_PATH`          | *(empty)*    | Set when served under a subpath, e.g. `/drydock` |
| `DRYDOCK_SESSION_HTTPS_ONLY` | `false`      | Set `true` behind an HTTPS proxy               |
| `DRYDOCK_SECRET_KEY`         | *(generated)* | Session signing key, saved in `/data` if not set |
| `DRYDOCK_HELPER_IMAGE`       | `busybox:stable` | Image that reads volume files when DryDock is not in a container (dev) |
| `DRYDOCK_FAIL2BAN_DB`        | `/var/lib/fail2ban/fail2ban.sqlite3` | fail2ban's database on the host |

Behind a reverse proxy, allow WebSocket upgrades so the container shell works. For nginx:

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

## Git

DryDock needs the repo's `.git` to commit, push and pull. When your Compose files sit in a sub-folder of the repo, mount the repo root and point `DRYDOCK_REPO_PATH` at the folder:

```yaml
    volumes:
      - /home/pi/homelab:/repo         # the git repo root
    environment:
      - DRYDOCK_REPO_PATH=/repo/docker # your Compose files
```

- A commit takes every change in the repo folder, `.env` files included unless `.gitignore` lists them. The Projects page lists them first.
- git runs as the owner of `.git`, so the files it writes stay yours.
- Commits use the repo's `user.name`. Without one, the author is the DryDock user.
- Push and pull use the git login for the remote's host. https remotes only: DryDock has no SSH keys.
- After a pull, apply the changes with **Reload** on each stack. DryDock never redeploys on its own.

## Reverse proxy

The proxy carries the traffic, not DryDock: a DryDock restart cuts nothing. Your Compose files get neutral labels:

```yaml
    labels:
      - expose.host=music.example.org   # several hosts: comma-separated
      - expose.port=3000                # the container port
      - expose.private=false            # default: private
```

The proxy stack runs DryDock's **proxy sync** next to the proxy. It reads these labels from the running containers and writes the proxy's config:

- **Traefik:** a file for Traefik's file provider, which Traefik watches.
- **SWAG** (nginx): one server block per service, checked with `nginx -t`, then reloaded.
- **Caddy:** the whole Caddyfile, loaded with `caddy reload`. Hosts are grouped under wildcard sites, so Caddy asks for one certificate per domain.

A config the proxy refuses is put back to the previous one, so a bad label never takes the proxy down. The labels are real Docker labels, so a plain `docker compose up` keeps them. To switch proxy, stop the old proxy stack and create the new one: your stacks stay as they are.

1. Point `*.<domain>` at your public IP (for example a CNAME to your dynamic DNS name), and forward ports 80 and 443 of the internet router to the Docker host.
2. On the **Proxy** page, set the domain. Then pick a proxy (Traefik, SWAG or Caddy) and how it gets its certificates:
   - **A DNS provider** (OVH, Cloudflare, or another one Traefik or SWAG knows by name): one wildcard certificate per domain, so your service names never appear in public certificate logs. It needs an API token that can edit the zone's DNS records (Let's Encrypt checks a TXT record). A dynamic DNS login is not enough.
   - **The HTTP challenge**: no DNS API, any domain. One certificate per name, through port 80; the names appear in public certificate logs. Traefik and Caddy only: SWAG would need every name up front.
3. Fill in the stack's `.env` tab (`LAN_RANGES`, `TRUSTED_IPS`, the token), stop any other proxy on ports 80 and 443, and run **up**.
   - SWAG reads the DNS token from a file: after the first up, fill in `PROXY_DATA/swag/dns-conf/<provider>.ini` and restart `swag`.
   - Caddy's official image has no DNS modules: with a DNS provider, the first up builds one. It takes a few minutes on a Pi. Caddy knows OVH and Cloudflare here.
   - Traefik with another provider passes the whole `.env` to Traefik: add the variables listed for it at <https://go-acme.github.io/lego/dns/>.
4. On a stack page, open **Expose**, pick a service, a name and its container port, then save and run **up**.

- **Private** services only answer an IP allowlist: `LAN_RANGES`, your current public IP and `TRUSTED_IPS`. The public IP is in it because LAN and VPN clients often come back through it (hairpin NAT). The sync refreshes it every 5 minutes. **Public** services answer everyone.
- Every service sends HSTS (`Strict-Transport-Security`): browsers stick to HTTPS for its name.
- One wildcard certificate covers every service, so your service names never appear in public certificate logs.
- Exposed services join the shared `proxy` network and keep their `default` one. The proxy reaches them by container name, so a recreate breaks nothing. **Remove** in the panel takes the labels and the network out again.
- A service with `network_mode: host` (Home Assistant) is reached through `host.docker.internal`, which the templates map to the host.
- fail2ban on the host reads the proxy's access log (`PROXY_DATA/logs/access.log`) and never bans the allowlist (`PROXY_DATA/allowlist.txt`). Set its jails on the **Host** page. The rules match a log format, not a proxy: text for Traefik and SWAG, JSON for Caddy.
- The panel rewrites the file in the editor, comments included, and shows the diff. Nothing is saved until you save. Older `traefik.*` or `swag*` labels on a service are replaced.

## Troubleshooting

See [docs/troubleshooting.md](docs/troubleshooting.md) for common problems, such as memory showing `0B / 0B`.

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
- Translated server messages: API errors and job output stay in English.
