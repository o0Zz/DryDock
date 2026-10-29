# Features

Everything DryDock does, by job. The [README](../README.md) has the short version.

## Run

- **Stacks:** every Compose file in your folder shows up as a project. Any `*.yml` file with a `services:` section counts. Start, stop, pull & build, reload or edit each one and its `.env`. **Pull & build** downloads newer images and rebuilds services that have a `build:` section. **Reload** stops the stack and runs `up`, so file changes apply. Create, rename, duplicate or delete a stack; a delete backs the stack up first. A `*.override.yml` next to a Compose file is merged in, like `docker compose up` does.
- **Containers:** start, stop, restart, pause, kill or rename. State, uptime, health check, restart count, CPU and memory with a 5-minute sparkline, ports, live logs, a detail page, and a shell in the browser.
- **Images:** see which images are in use, and remove or prune the rest.
- **Volumes:** named volume management. Admins can browse the files in a volume (read-only) and download them.
- **Networks:** driver, subnet and attached containers of every network. Remove one, or prune the custom networks no container uses. Networks of stopped stacks are kept, unlike `docker network prune`.
- **Background jobs:** scans, update checks, stack actions and prunes run in the background. The top bar shows progress from any page. Compose commands run in a short-lived helper container, so DryDock can update its own stack and come back.

## Expose

- **Host names:** give a service a host name (`jellyfin.example.org`) with HTTPS, private (an IP allowlist) or public. The **Services** panel beside the Compose editor writes neutral `expose.*` labels that name no proxy.
- **Proxy page:** every host name in your Compose files, with its stack, service, container port, visibility and state, plus the health of the proxy and its sync. A host name already used by another stack is refused.
- **Your choice of proxy:** stack templates for Traefik, SWAG (nginx) or Caddy, each with a wildcard certificate. The labels work with all three. See [Reverse proxy](reverse-proxy.md).

## Secure

- **CVE scans:** scan one image, all running images, or all images in your Compose files.
- **Image updates:** finds rebuilt tags (`latest`, `stable`) and newer versions (`2025.10.4` → `2026.10.2`). A service built from a git URL (`build: https://github.com/me/app.git#main`) shows an update when its ref gets a new commit, and Update rebuilds it. For `postgres:16.2` you see both the newest `16.x` and the newest overall. For a floating tag like `stable`, the containers list shows the version the image declares (`org.opencontainers.image.version` label), when it has one.
- **Auto-update (opt-in):** tick **Auto-update** for a service in the **Services** panel (it writes the label `drydock.update: auto`) and turn on Auto-update in Settings. Every day at the hour you pick, DryDock pulls and recreates the running labelled services whose tag was rebuilt or whose git ref moved. It never applies a newer version tag, never starts a stopped stack, and leaves every other service alone. Good for a proxy or DryDock itself, not for Home Assistant or a database. After the recreate it waits for the container to run without restarts and pass its healthcheck, and the webhook gets what was updated and what failed. The old image stays, so you can roll back by hand.
- **Host updates:** pending OS package updates on the host (Debian, Ubuntu, Raspberry Pi OS), with security updates and "reboot required" flagged on the dashboard. They are checked on the update check schedule, read-only: DryDock never installs anything. The page gives the command to run on the host, and says when automatic security updates (`unattended-upgrades`) are off.
- **fail2ban:** on the **Proxy** page, **Security** tab, admins see every jail of the host, sshd included. Each jail shows its log, `maxretry`, `findtime`, `bantime` and bans (now, in history, last), then the raw blocks of `/etc/fail2ban` that define it, in the order fail2ban reads them: the last value of a key wins. The package's `.conf` files are read only, since apt replaces them; a change goes in the `.local` file after them (`jail.local`, `filter.d/sshd.local`), and a block goes back where it was, comments kept. "Copy" puts every block with its file on the clipboard, to paste into an AI and paste the answer back. A new jail starts from a template (failed logins, refused requests, scanners, bad bots, unknown host names) and gets its own `jail.d/<name>.local` and `filter.d/<name>.conf`. Test a filter, as edited, on the end of its log, preview the changed files as a diff, then apply: DryDock backs up the files, fail2ban checks the config, and a refused config is put back. Bans block the proxy's forwarded traffic, not only the host's own ports. The ban history, the user names tried on SSH and the log lines behind each ban are below. No unban yet.
- **IP blocklist:** on the same tab, admins turn on a list of known bad IPs (FireHOL level1, or their own list URLs). DryDock downloads it every 24 hours and at startup, drops private ranges, and loads it in its own nftables table on the host (`inet drydock_blocklist`). The page shows the ranges loaded, the packets dropped, and checks whether an IP is blocked. The host needs `nft` (nftables).
- **Schedules and alerts:** run scans and update checks on an interval, and send results to a webhook.
- **Users and API tokens:** several users with an admin flag. Each user can create tokens on the Settings page for scripts and CI, e.g. `curl -H "Authorization: Bearer ddt_..." http://drydock:8080/api/containers`. A token has the rights of its user.

## Tools

- **Private registries:** admins save a login per registry (Docker Hub, GHCR, your own) on the Settings page. Update checks, pulls and scans use it. DryDock checks the login with the registry before it saves it.
- **Git logins:** admins save a login per git host (GitHub, Gitea, your own) on the Settings page. Builds from a private git URL and their update checks use it, with no token in your Compose files. Given a repo URL, DryDock checks the login before it saves it.
- **Git for the repo folder:** when your Compose folder is in a git repo, the Projects page lists the changes and has **Commit & push** and **Pull** (fast-forward only), for admins. See [Git](git.md).
- **AI assistant:** a chat beside the Compose editor. Ask for a change ("add a healthcheck to web"), see the diff, apply it to the editor, then save as usual. Nothing is saved for you. Admins pick the provider on the Settings page: OpenAI (or any OpenAI-compatible server, such as Ollama), Anthropic with an API key, or GitHub Copilot with a GitHub sign-in. Only the Compose file is sent, never the `.env`.
- **English and French:** pick the language in the top bar; it defaults to your browser's. Works on a phone too: the menu folds into a drawer.
- **Logs page:** DryDock's own log, to see why a scan or a check failed.
