# syntax=docker/dockerfile:1.7

# ---------- Stage 0: version ----------
# CI passes APP_VERSION. A local `docker compose build` does not, so it is
# computed here from .git with the same rule as CI: release/X.Y.Z gives
# X.Y.Z+<commit count>, a vX.Y.Z tag gives X.Y.Z, any other branch gives
# 0.0.0-<branch>+<commit count>.
# A git URL build context has no .git unless the build passes
# BUILDKIT_CONTEXT_KEEP_GIT_DIR=1. An ARG here cannot turn it on.
FROM --platform=$BUILDPLATFORM alpine:3.22 AS version
ARG APP_VERSION
RUN apk add --no-cache git
# The wildcard keeps the build working without a .git (a source archive):
# a COPY whose only source is missing fails. A wildcard copies the directory's
# contents, hence --git-dir below.
COPY backend/pyproject.toml .gi[t] /src/git/
RUN set -eu; \
    g() { git --git-dir=/src/git "$@"; }; \
    version="${APP_VERSION:-}"; \
    if [ -z "$version" ] && g rev-parse -q --verify HEAD >/dev/null 2>&1; then \
        # A git URL context is a shallow clone. Fetch the rest of the history,
        # commits only, to count them. Offline, the count is the clone's depth.
        if [ "$(g rev-parse --is-shallow-repository)" = true ]; then \
            g fetch -q --unshallow --filter=tree:0 origin || true; \
        fi; \
        count=$(g rev-list --count HEAD); \
        branch=$(g rev-parse --abbrev-ref HEAD); \
        # Its HEAD is also detached, with the ref it was built from as a branch.
        if [ "$branch" = HEAD ]; then \
            branch=$(g for-each-ref --points-at HEAD --count 1 --format '%(refname:lstrip=2)' refs/heads); \
            branch="${branch:-HEAD}"; \
        fi; \
        release=$(printf '%s' "$branch" | sed -nE 's#^release/([0-9]+\.[0-9]+(\.[0-9]+)?).*#\1#p'); \
        if printf '%s' "$branch" | grep -qE '^v[0-9]+\.[0-9]+\.[0-9]+'; then \
            version="${branch#v}"; \
        elif [ -n "$release" ]; then \
            # release/X.Y counts as X.Y.0.
            case "$release" in *.*.*) ;; *) release="$release.0" ;; esac; \
            version="$release+$count"; \
        else \
            # Semver pre-release identifiers only allow [0-9A-Za-z-].
            version="0.0.0-$(printf '%s' "$branch" | tr -c '0-9A-Za-z-' '-')+$count"; \
        fi; \
    fi; \
    echo "${version:-0.0.0-dev}" > /version; \
    echo "Version: $(cat /version)"


# ---------- Stage 1: build the frontend ----------
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN --mount=type=cache,target=/root/.npm \
    if [ -f package-lock.json ]; then npm ci; else npm install; fi
COPY frontend/ ./
# Copied last: a new commit only rebuilds the frontend when the version changes.
COPY --from=version /version /version
RUN APP_VERSION="$(cat /version)" npm run build


# ---------- Stage 2: build the backend + install deps ----------
FROM ghcr.io/astral-sh/uv:0.13-python3.11-trixie-slim AS backend
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
FROM python:3.11-slim-trixie AS runtime

ARG TARGETARCH
# These are Go binaries that embed their own Go stdlib, so stale versions are
# the main source of CVEs in this image. Keep them current.
ARG TRIVY_VERSION=0.76.0
ARG DOCKER_VERSION=29.9.1
ARG COMPOSE_VERSION=5.6.0
ARG BUILDX_VERSION=0.38.0

# Install docker CLI + compose and buildx plugins + trivy from static binaries.
# We deliberately avoid Docker's apt repository (gpg --dearmor is flaky
# under QEMU emulation) and pull prebuilt binaries instead.
# Use bash with pipefail so a failed curl in a `curl | tar` pipe fails the
# RUN with curl's error instead of tar's generic exit code 2.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
RUN set -eux; \
    apt-get update; \
    # Pick up Debian security fixes published after the base image was built.
    apt-get upgrade -y; \
    # git: commit, push and pull of the repo folder (repo_git_service).
    apt-get install -y --no-install-recommends ca-certificates curl git tini; \
    case "${TARGETARCH:-amd64}" in \
        amd64) DOCKER_ARCH=x86_64;  COMPOSE_ARCH=x86_64;  BUILDX_ARCH=amd64;  TRIVY_ARCH=64bit ;; \
        arm64) DOCKER_ARCH=aarch64; COMPOSE_ARCH=aarch64; BUILDX_ARCH=arm64;  TRIVY_ARCH=ARM64 ;; \
        arm)   DOCKER_ARCH=armhf;   COMPOSE_ARCH=armv7;   BUILDX_ARCH=arm-v7; TRIVY_ARCH=ARM ;; \
        *)     DOCKER_ARCH=x86_64;  COMPOSE_ARCH=x86_64;  BUILDX_ARCH=amd64;  TRIVY_ARCH=64bit ;; \
    esac; \
    # Docker CLI (static bundle contains the full client; keep only `docker`)
    curl -fsSL "https://download.docker.com/linux/static/stable/${DOCKER_ARCH}/docker-${DOCKER_VERSION}.tgz" \
        | tar -xz -C /usr/local/bin --strip-components=1 docker/docker; \
    # Compose plugin
    install -m 0755 -d /usr/local/lib/docker/cli-plugins; \
    curl -fsSL "https://github.com/docker/compose/releases/download/v${COMPOSE_VERSION}/docker-compose-linux-${COMPOSE_ARCH}" \
        -o /usr/local/lib/docker/cli-plugins/docker-compose; \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose; \
    # Buildx plugin. Without it Compose falls back to the classic builder, which
    # needs a local git for a git URL build context and has no RUN --mount.
    curl -fsSL "https://github.com/docker/buildx/releases/download/v${BUILDX_VERSION}/buildx-v${BUILDX_VERSION}.linux-${BUILDX_ARCH}" \
        -o /usr/local/lib/docker/cli-plugins/docker-buildx; \
    chmod +x /usr/local/lib/docker/cli-plugins/docker-buildx; \
    # Trivy CVE scanner
    curl -fsSL "https://github.com/aquasecurity/trivy/releases/download/v${TRIVY_VERSION}/trivy_${TRIVY_VERSION}_Linux-${TRIVY_ARCH}.tar.gz" \
        | tar -xz -C /usr/local/bin trivy; \
    docker --version; docker compose version; docker buildx version; trivy --version; \
    apt-get purge -y curl; \
    apt-get autoremove -y; \
    rm -rf /var/lib/apt/lists/*; \
    # The app runs from its own venv, which has no pip. The system pip,
    # setuptools and wheel are unused and carry known CVEs.
    python -m pip uninstall -y setuptools wheel pip || true

WORKDIR /app

# Copy the fully-populated venv + app source from the backend stage
COPY --from=backend /app/.venv /app/.venv
COPY --from=backend /app/app /app/app
# Alembic revisions, applied automatically at startup (app/core/migrations.py).
COPY backend/migrations /app/migrations
COPY backend/alembic.ini /app/alembic.ini
# Read by app/core/config.py; DRYDOCK_VERSION still overrides it.
COPY --from=version /version /app/VERSION
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONPATH=/app \
    PYTHONUNBUFFERED=1 \
    DRYDOCK_REPO_PATH=/repo \
    DRYDOCK_DATA_PATH=/data

# Frontend build output — served as static files by FastAPI
COPY --from=frontend /build/dist /app/static

RUN mkdir -p /data /repo

EXPOSE 8080

ENTRYPOINT ["/usr/bin/tini", "--"]
# --proxy-headers lets a reverse proxy pass through the real scheme/client IP.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
