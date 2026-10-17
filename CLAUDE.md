# DryDock

DryDock is a lightweight, self-hosted Docker management UI designed for homelabs and Raspberry Pi setups.

The goal is to build a simple all-in-one alternative to tools like Portainer, focused on managing Docker Compose files from a mounted repository, checking image updates, scanning for CVEs, and providing a clean web UI for day-to-day container operations.

## Project Goal

DryDock allows the user to mount a local folder containing Docker Compose YAML files and manage everything from a browser.

Core features:

* Browse a mounted repository of Docker Compose projects
* View and edit `docker-compose.yml` files
* Start, stop, restart, pull and redeploy Compose stacks
* View live container logs
* List running containers
* Detect available image updates
* Scan Docker images for CVEs
* Store scan results, stack metadata and history in SQLite
* Run as a single Docker image

The project is intended to be simple, local-first, and easy to deploy on a Raspberry Pi.

## Target Environment

Primary target:

* Raspberry Pi
* Docker / Docker Compose
* Local LAN usage
* Homelab / self-hosted services

DryDock should not require Kubernetes, cloud services, or a complex external database.

## Tech Stack

### Backend

* Python
* FastAPI
* SQLite
* Docker SDK for Python, also known as `docker-py`
* Subprocess calls to `docker compose` for Compose stack operations
* Trivy CLI for CVE scanning
* Optional: APScheduler or a lightweight background worker for scheduled scans and update checks

The backend exposes a REST API and real-time log streaming endpoints.

### Frontend

* React
* Vite
* TypeScript preferred
* Simple dashboard-style UI
* Monaco Editor or CodeMirror for YAML editing
* WebSocket or Server-Sent Events for live logs

### Database

* SQLite
* Stored inside a persistent `/data` volume

SQLite is used for:

* Registered Compose projects
* Scan history
* Update check history
* User settings
* Container metadata cache
* Optional audit/history of actions

### Packaging

DryDock should run as a single Docker image.

Expected container mounts:

```yaml
volumes:
  - /var/run/docker.sock:/var/run/docker.sock
  - /path/to/compose-repo:/repo
  - drydock_data:/data
```

The mounted `/repo` folder contains the user’s Docker Compose projects.

The mounted Docker socket allows DryDock to inspect containers, stream logs, and interact with Docker.

## High-Level Architecture

```text
Browser UI
   |
   | REST / WebSocket / SSE
   v
FastAPI Backend
   |
   |-- Docker SDK for Python / docker-py
   |     - list containers
   |     - inspect containers
   |     - stream logs
   |
   |-- docker compose CLI
   |     - up
   |     - down
   |     - pull
   |     - restart
   |
   |-- Trivy CLI
   |     - scan Docker images for CVEs
   |
   |-- SQLite
         - projects
         - scans
         - update checks
         - settings
```

## Compose Repository Model

DryDock expects a mounted folder such as `/repo`.

Example structure:

```text
/repo
  /homeassistant
    docker-compose.yml
  /nginx-proxy
    docker-compose.yml
  /uptime-kuma
    compose.yml
  /paperless
    docker-compose.yml
```

The app should recursively discover Compose files named:

* `docker-compose.yml`
* `docker-compose.yaml`
* `compose.yml`
* `compose.yaml`

Each discovered Compose file becomes a “Project” in the UI.

## MVP Features

### 1. Project Discovery

The backend scans `/repo` and finds Compose files.

For each project, store:

* Project name
* Compose file path
* Last modified date
* Services defined in the file
* Related containers if running

### 2. YAML Editor

The UI allows editing the Compose file.

Important behavior:

* Always make a backup before saving
* Validate YAML before saving
* Ideally validate basic Compose structure
* Show clear errors if YAML is invalid

Backups can be stored in:

```text
/data/backups
```

### 3. Stack Actions

For each Compose project, provide buttons:

* Pull
* Up / Deploy
* Down
* Restart
* Stop
* View logs

Initial implementation can call the Docker Compose CLI using subprocess:

```bash
docker compose -f /repo/example/docker-compose.yml up -d
docker compose -f /repo/example/docker-compose.yml down
docker compose -f /repo/example/docker-compose.yml pull
docker compose -f /repo/example/docker-compose.yml logs -f
```

This avoids reimplementing Docker Compose behavior in Python.

### 4. Container List

Use `docker-py` to list containers.

Show:

* Name
* Image
* Status
* Ports
* Created date
* Compose project label if available
* Restart policy
* CPU/RAM usage later if possible

### 5. Live Logs

The UI should support live logs for:

* A single container
* A Compose project

Implementation options:

* WebSocket
* Server-Sent Events

Start simple with Server-Sent Events if easier.

### 6. CVE Scanning

Use Trivy CLI.

Example:

```bash
trivy image --format json nginx:latest
```

The backend should parse the JSON result and store a summary in SQLite.

For each image, show:

* Image name
* Last scanned date
* Critical CVE count
* High CVE count
* Medium CVE count
* Whether a fixed version exists
* Link/reference to CVE where available

Initial scan modes:

* Scan one image manually
* Scan all images used by running containers
* Scan all images referenced in Compose files

### 7. Update Checks

The app should detect if a newer image is available.

Initial simple approach:

* Run `docker compose pull` in dry/safe mode where possible, or
* Compare local and remote image digests using registry inspection tools later

For MVP, it is acceptable to start with:

* “Pull available” button
* Store last pull/check timestamp
* Later add real digest comparison

### 8. Dashboard

Dashboard should show:

* Number of running containers
* Number of stopped containers
* Number of Compose projects
* Images with critical CVEs
* Images with high CVEs
* Images with possible updates
* Last scan time

## Security Notes

DryDock mounts the Docker socket:

```text
/var/run/docker.sock
```

This effectively gives the app root-equivalent control over the Docker host.

Therefore:

* Do not expose DryDock directly to the internet
* Use it only on LAN, VPN, Tailscale, or WireGuard
* Add authentication before any serious use
* Consider read-only modes for some features later
* Be careful with editing arbitrary files under `/repo`

## Authentication

Add an authentication mechanism: 
* Single admin user
* Password stored securely
* Session cookie
* Reverse proxy support

## Suggested Backend Structure

```text
backend/
  app/
    main.py
    api/
      projects.py
      containers.py
      logs.py
      scans.py
      updates.py
      settings.py
    core/
      config.py
      database.py
      security.py
    services/
      docker_service.py
      compose_service.py
      trivy_service.py
      repo_service.py
      update_service.py
    models/
      project.py
      scan.py
      settings.py
    schemas/
      project.py
      scan.py
      container.py
  pyproject.yaml
```

## Suggested Frontend Structure

```text
frontend/
  src/
    api/
    components/
    pages/
      Dashboard.tsx
      Projects.tsx
      ProjectDetail.tsx
      Containers.tsx
      Scans.tsx
      Settings.tsx
    hooks/
    types/
    main.tsx
```

## Initial API Ideas

```text
GET    /api/projects
GET    /api/projects/{id}
GET    /api/projects/{id}/compose
PUT    /api/projects/{id}/compose
POST   /api/projects/{id}/up
POST   /api/projects/{id}/down
POST   /api/projects/{id}/pull
POST   /api/projects/{id}/restart

GET    /api/containers
GET    /api/containers/{id}
POST   /api/containers/{id}/start
POST   /api/containers/{id}/stop
POST   /api/containers/{id}/restart

GET    /api/logs/container/{id}
GET    /api/logs/project/{id}

POST   /api/scans/image
POST   /api/scans/running
GET    /api/scans
GET    /api/scans/{id}

POST   /api/updates/check
GET    /api/updates
```

## Development Priorities

Build in this order:

1. Backend project discovery from `/repo`
2. Frontend project list
3. Compose YAML viewer/editor
4. Compose actions: up, down, pull, restart
5. Container list using `docker-py`
6. Live logs
7. Trivy scan for one image
8. Trivy scan for all running images
9. Dashboard CVE summary
10. Update checks
11. Authentication
12. Scheduled scans and notifications

## Non-Goals for MVP

Do not build these at first:

* Kubernetes support
* Multi-host Docker management
* Full registry mirror support
* Role-based access control
* Complex auto-update engine
* Public internet exposure
* Plugin system
* Full Portainer replacement

DryDock should start as a focused, local Docker Compose manager.

## Design Principles

* Simple over complete
* Local-first
* Raspberry Pi friendly
* One Docker image
* Minimal dependencies
* Safe defaults
* Manual approval before destructive actions
* Back up YAML files before editing
* Never auto-update critical services by default

## Example Deployment

```yaml
services:
  drydock:
    image: drydock/drydock:latest
    container_name: drydock
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - /home/pi/docker:/repo
      - drydock_data:/data
    environment:
      - TZ=Europe/Paris
      - DRYDOCK_REPO_PATH=/repo
      - DRYDOCK_DATA_PATH=/data

volumes:
  drydock_data:
```

## Project Name

Project name: DryDock

Meaning:

A dry dock is where ships are pulled out of the water to be inspected, repaired and repainted before going back out. DryDock is the same idea for Docker Compose stacks: the place where they live, can be edited, monitored, updated and scanned.

Alternative names considered:

* HarborGuard
* StackNest
* DockPilot
* ComposeHub
* HarborLite
* DockYard
* PiDock
* StackGuard
* DockWatch
* ComposeKeeper
* DockPanel

DryDock is preferred because it is short, friendly, self-hosted oriented, evokes inspection and maintenance, and is not limited only to Raspberry Pi.
