# syntax=docker/dockerfile:1.7

# ---------- Stage 1: build the frontend ----------
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm \
    if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
RUN npm run build


# ---------- Stage 2: build the backend + install deps ----------
FROM ghcr.io/astral-sh/uv:0.9-python3.11-bookworm-slim AS backend
WORKDIR /app
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never

# Install deps first for cache reuse
COPY backend/pyproject.toml backend/uv.lock* ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project 2>/dev/null || \
    uv sync --no-dev --no-install-project

# Then copy source and install the project
COPY backend/app ./app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --no-dev --frozen 2>/dev/null || uv sync --no-dev


# ---------- Stage 3: runtime ----------
FROM python:3.11-slim-bookworm AS runtime

ARG TARGETARCH
ARG TRIVY_VERSION=0.72.0
ARG DOCKER_VERSION=27.4.1
ARG COMPOSE_VERSION=2.32.1

# Install docker CLI + compose plugin + trivy from static binaries.
# We deliberately avoid Docker's apt repository (gpg --dearmor is flaky
# under QEMU emulation) and pull prebuilt binaries instead.
# Use bash with pipefail so a failed curl in a `curl | tar` pipe fails the
# RUN with curl's error instead of tar's generic exit code 2.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl tini; \
    case "${TARGETARCH:-amd64}" in \
        amd64) DOCKER_ARCH=x86_64;  COMPOSE_ARCH=x86_64;  TRIVY_ARCH=64bit ;; \
        arm64) DOCKER_ARCH=aarch64; COMPOSE_ARCH=aarch64; TRIVY_ARCH=ARM64 ;; \
        arm)   DOCKER_ARCH=armhf;   COMPOSE_ARCH=armv7;   TRIVY_ARCH=ARM ;; \
        *)     DOCKER_ARCH=x86_64;  COMPOSE_ARCH=x86_64;  TRIVY_ARCH=64bit ;; \
    esac; \
    # Docker CLI (static bundle contains the full client; keep only `docker`)
    curl -fsSL "https://download.docker.com/linux/static/stable/${DOCKER_ARCH}/docker-${DOCKER_VERSION}.tgz" \
        | tar -xz -C /usr/local/bin --strip-components=1 docker/docker; \
    # Compose v2 plugin
    install -m 0755 -d /usr/local/lib/docker/cli-plugins; \
    curl -fsSL "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-${COMPOSE_ARCH}" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose; \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose; \
    # Trivy CVE scanner
    curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz" \
        | tar -xz -C /usr/local/bin trivy; \
    docker --version; docker compose version; trivy --version; \
    apt-get purge -y curl; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the fully-populated venv + app source from the backend stage
COPY --from=backend /app/.venv /app/.venv
COPY --from=backend /app/app /app/app
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    HARBORGUARD_REPO_PATH=/repo \
    HARBORGUARD_DATA_PATH=/data

# Frontend build output — served as static files by FastAPI
COPY --from=frontend /build/dist /app/static

RUN mkdir -p /data /repo

EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
