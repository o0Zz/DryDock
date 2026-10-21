from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from docker.types import Mount

from app.core.config import settings
from app.services import (
    docker_service,
    git_auth_service,
    git_service,
    host_path_service,
    job_service,
    registry_auth_service,
    repo_service,
)
from app.services.job_service import JobContext
from app.services.repo_service import COMPOSE_FILENAMES

logger = logging.getLogger(__name__)

ALLOWED_ACTIONS = {"up", "down", "pull", "reload", "stop"}


class ComposeError(Exception):
    """Raised for compose-service errors that map cleanly to HTTP failures."""


class ComposeExists(ComposeError):
    """Raised when a stack's name or target path is already taken."""


def read_compose(compose_path: Path) -> str:
    return compose_path.read_text(encoding="utf-8")


def validate_yaml(content: str) -> None:
    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ComposeError(f"Invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ComposeError("Compose file must be a YAML mapping at the root")
    if "services" not in data or not isinstance(data["services"], dict):
        raise ComposeError("Compose file must contain a 'services' mapping")


def backup_dir(project_id: str) -> Path:
    path = settings.backups_path / project_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def backup_stamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")


def _backup(project_id: str, path: Path, extension: str) -> Path:
    backup_path = backup_dir(project_id) / f"{backup_stamp()}{extension}"
    shutil.copy2(path, backup_path)
    logger.info("Backed up %s to %s", path, backup_path)
    return backup_path


def write_compose(project_id: str, compose_path: Path, content: str) -> Path:
    validate_yaml(content)
    backup = _backup(project_id, compose_path, compose_path.suffix)
    compose_path.write_text(content, encoding="utf-8")
    return backup


# --- .env ----------------------------------------------------------------------

# `KEY=value`, `export KEY=value`, Compose's `KEY: value`, or a bare `KEY`.
_ENV_ASSIGNMENT = re.compile(
    r"^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_.-]*\s*(?:[=:](?P<value>.*))?$"
)


def _env_path(compose_path: Path) -> Path:
    """The `.env` Compose reads for this file: the one in the project folder.
    Stacks that share a folder share it too."""
    return compose_path.parent / ".env"


def read_env(compose_path: Path) -> str | None:
    path = _env_path(compose_path)
    return path.read_text(encoding="utf-8") if path.is_file() else None


def _closes(value: str, quote: str) -> bool:
    """Whether a quoted value that opened earlier ends in `value`."""
    index = 0
    while (index := value.find(quote, index)) != -1:
        if quote == "'" or value[index - 1 : index] != "\\":
            return True
        index += 1
    return False


def _validate_env(content: str) -> None:
    """Check the dotenv syntax Compose accepts, so a typo fails here, not on the next `up`."""
    open_quote: tuple[str, int] | None = None
    for number, line in enumerate(content.splitlines(), start=1):
        if open_quote:
            if _closes(line, open_quote[0]):
                open_quote = None
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ENV_ASSIGNMENT.match(line)
        if match is None:
            raise ComposeError(f"Line {number}: expected KEY=value, got {stripped[:40]!r}")
        value = (match["value"] or "").strip()
        # Double and single quotes may span lines; the value ends at the matching quote.
        if value[:1] in ("'", '"') and not _closes(value[1:], value[0]):
            open_quote = (value[0], number)
    if open_quote:
        raise ComposeError(f"Line {open_quote[1]}: quoted value is never closed")


def write_env(project_id: str, compose_path: Path, content: str) -> Path | None:
    """Validate, back up the current file if there is one, then write. Returns the backup."""
    _validate_env(content)
    path = _env_path(compose_path)
    backup = _backup(project_id, path, ".env") if path.is_file() else None
    path.write_text(content, encoding="utf-8")
    return backup


def create_compose(name: str, content: str) -> Path:
    """Create `<repo>/<name>/docker-compose.yml`. `name` must already be a safe
    single path segment (the API schema enforces it)."""
    validate_yaml(content)
    project_dir = settings.repo_path / name
    if any((project_dir / filename).exists() for filename in COMPOSE_FILENAMES):
        raise ComposeExists(f"A compose file already exists in '{name}/'")
    project_dir.mkdir(parents=True, exist_ok=True)
    compose_path = project_dir / "docker-compose.yml"
    compose_path.write_text(content, encoding="utf-8")
    logger.info("Created new stack %s", compose_path)
    return compose_path


def override_path(compose_path: Path) -> Path | None:
    """The `<stem>.override.y(a)ml` next to a Compose file, if any. Passing -f turns
    off Compose's own override merge, so it has to be added back explicitly."""
    for suffix in (".yml", ".yaml"):
        candidate = compose_path.with_name(f"{compose_path.stem}.override{suffix}")
        if candidate.is_file():
            return candidate
    return None


@dataclass(frozen=True)
class GitSecrets:
    # The extra Compose file that declares the secrets.
    file: Path
    # Environment variable -> file with its value (an `Authorization` header).
    variables: dict[str, Path]

    def environment(self) -> dict[str, str]:
        return {name: path.read_text(encoding="utf-8") for name, path in self.variables.items()}

    def exports(self) -> str:
        """Shell that sets the variables from the files, so the helper container's
        config never holds a token."""
        return " && ".join(
            f'export {name}="$(cat {shlex.quote(path.as_posix())})"'
            for name, path in self.variables.items()
        )


def git_secrets(files: list[Path]) -> GitSecrets | None:
    """A Compose file that hands git logins to the builds that clone a private repo.

    BuildKit fetches a git build context with the `GIT_AUTH_HEADER.<host>`
    build secret when the build has one. This file declares that secret for
    each service built from a host with a stored login, so the user's Compose
    files need no token. None when no service needs one.

    The secrets come from environment variables, not files: bake refuses to
    read a file outside the project unless it is granted `--allow fs.read`,
    which older Compose versions do not pass.
    """
    builds: dict[str, str] = {}
    for path in files:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) if path.is_file() else None
        services = data.get("services") if isinstance(data, dict) else None
        for name, spec in (services or {}).items():
            source = git_service.parse_build(spec.get("build") if isinstance(spec, dict) else None)
            if source is not None and source.url.startswith("https://"):
                builds[str(name)] = git_auth_service.normalize(source.url)
    hosts = sorted({host for host in builds.values() if git_auth_service.credentials(host)})
    if not hosts:
        return None
    index = {host: number for number, host in enumerate(hosts)}
    content = yaml.safe_dump(
        {
            "secrets": {
                f"drydock_git_{index[host]}": {"environment": f"DRYDOCK_GIT_AUTH_{index[host]}"}
                for host in hosts
            },
            "services": {
                name: {
                    "build": {
                        "secrets": [
                            {
                                "source": f"drydock_git_{index[host]}",
                                "target": f"GIT_AUTH_HEADER.{host}",
                            }
                        ]
                    }
                }
                for name, host in builds.items()
                if host in index
            },
        },
        sort_keys=False,
    )
    # Under /data, which the Compose helper container shares.
    path = settings.data_path / "git" / "compose" / f"{repo_service.project_id(files[0])}.yml"
    if not path.is_file() or path.read_text(encoding="utf-8") != content:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    variables = {
        f"DRYDOCK_GIT_AUTH_{index[host]}": git_auth_service.header_path(host) for host in hosts
    }
    return GitSecrets(file=path, variables=variables)


def _files(compose_path: Path) -> list[Path]:
    override = override_path(compose_path)
    return [compose_path] if override is None else [compose_path, override]


def _git_secrets(compose_path: Path) -> GitSecrets | None:
    try:
        return git_secrets(_files(compose_path))
    except (OSError, yaml.YAMLError) as exc:
        # Compose reports a broken file itself, with a better message.
        logger.debug("No git secrets for %s: %s", compose_path, exc)
        return None


def _command(
    compose_path: Path,
    args: list[str],
    project_name: str | None = None,
    secrets: GitSecrets | None = None,
) -> list[str]:
    command = ["docker", "compose"]
    for path in _files(compose_path):
        command += ["-f", str(host_path_service.to_host(path))]
    if secrets is not None:
        command += ["-f", str(secrets.file)]
    if project_name:
        command += ["-p", project_name]
    return command + args


def _compose(
    compose_path: Path,
    args: list[str],
    *,
    project_name: str | None = None,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    # Through the host-path alias, so relative bind mounts resolve on the host.
    secrets = _git_secrets(compose_path)
    command = _command(compose_path, args, project_name, secrets)
    logger.info("Running: %s", " ".join(command))
    # Registry credentials for pulls, git logins for builds.
    env = registry_auth_service.subprocess_env()
    if secrets is not None:
        env = {**(env or os.environ), **secrets.environment()}
    try:
        return subprocess.run(  # noqa: S603 — args list, no shell
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=host_path_service.to_host(compose_path).parent,
            env=env,
        )
    except FileNotFoundError as exc:
        raise ComposeError("`docker` CLI not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ComposeError(f"`docker compose {args[0]}` timed out after {timeout}s") from exc


# Pulling a large image on a Pi over a slow link easily takes several minutes.
PULL_TIMEOUT = 1800


def _timeout(args: list[str]) -> int:
    # `up` pulls missing images and builds take long on a Pi: same budget as a pull.
    return PULL_TIMEOUT if args[0] in ("up", "pull", "build") else 300


def _helper_parent(ctx: JobContext | None) -> str | None:
    """DryDock's own container, when a copy of it should run this job's Compose commands.

    A job runs Compose in a helper container (see `_run_in_helper`), so the
    run survives DryDock stopping. Outside Docker (dev) and outside a job,
    Compose runs as a plain subprocess.
    """
    if ctx is None:
        return None
    container_id = host_path_service.own_container_id()
    try:
        if container_id and docker_service.container_image(container_id):
            return container_id
    except docker_service.DockerUnavailable as exc:
        raise ComposeError(f"Docker is unavailable: {exc}") from exc
    return None


def _run_in_helper(
    compose_path: Path,
    steps: list[list[str]],
    *,
    project_name: str | None,
    ctx: JobContext,
    parent: str,
) -> subprocess.CompletedProcess[str]:
    """Run Compose steps one after the other in a helper container, until one fails.

    Compose stops a container before it creates its replacement. When that
    container is DryDock, a Compose process inside it dies with it and the
    stack stays down. The helper is a separate container, so it carries on.
    """
    secrets = _git_secrets(compose_path)
    commands = [shlex.join(_command(compose_path, args, project_name, secrets)) for args in steps]
    script = " && ".join(([secrets.exports()] if secrets else []) + commands)
    # The helper lacks DryDock's host-path symlink: mount the repo at that path instead.
    host_repo = host_path_service.to_host(settings.repo_path)
    mounts = []
    if host_repo != settings.repo_path:
        path = host_repo.as_posix()
        mounts.append(Mount(target=path, source=path, type="bind", read_only=True))
    env = registry_auth_service.subprocess_env() or {}
    environment = {"DOCKER_CONFIG": env["DOCKER_CONFIG"]} if "DOCKER_CONFIG" in env else {}
    logger.info("Running in a helper container: %s", script)
    try:
        helper = docker_service.start_compose_helper(
            script,
            job_id=ctx.job.id,
            parent_id=parent,
            mounts=mounts,
            working_dir=host_path_service.to_host(compose_path).parent.as_posix(),
            environment=environment,
        )
    except (docker_service.DockerNotFound, docker_service.DockerUnavailable) as exc:
        raise ComposeError(f"Could not start the docker compose helper: {exc}") from exc
    exit_code, output = follow(helper, ctx, timeout=sum(_timeout(args) for args in steps))
    # docker logs mixes both streams; Compose writes its progress to stderr.
    return subprocess.CompletedProcess(script, exit_code, stdout="", stderr=output)


def follow(helper_id: str, ctx: JobContext, *, timeout: int = PULL_TIMEOUT) -> tuple[int, str]:
    """Wait for a Compose helper, keeping the job output up to date. Removes it at the end.

    Returns the exit code and the output. Raises job_service.Interrupted when
    DryDock shuts down first: the helper goes on, and the next start resumes the job.
    """
    output = ""

    def show(text: str) -> None:
        nonlocal output
        output = text
        ctx.set_output(text)

    try:
        exit_code = docker_service.follow_helper(
            helper_id, show, timeout=timeout, stop=job_service.stopping
        )
    except TimeoutError as exc:
        docker_service.remove_helper(helper_id)
        raise ComposeError(f"`docker compose` timed out after {timeout}s") from exc
    except (docker_service.DockerNotFound, docker_service.DockerUnavailable) as exc:
        raise ComposeError(f"Lost track of the docker compose helper: {exc}") from exc
    if exit_code is None:
        raise job_service.Interrupted(f"DryDock stopped while helper {helper_id} ran")
    docker_service.remove_helper(helper_id)
    return exit_code, output


def run_action(
    compose_path: Path,
    action: str,
    *,
    project_name: str | None = None,
    ctx: JobContext | None = None,
) -> dict:
    if action not in ALLOWED_ACTIONS:
        raise ComposeError(f"Unsupported action: {action}")

    # `reload` applies an edited Compose file. `docker compose restart` would not:
    # it restarts the existing containers with the config they were created with.
    # `up` after the stop recreates the services whose config changed.
    if action == "reload":
        steps = [["stop"], ["up", "-d"]]
    elif action == "pull":
        # A plain pull fails on services with `build:` (it looks for the built image
        # in a registry). Pull the rest, then rebuild those on fresh base images.
        # `build` is a no-op for stacks without `build:` services.
        steps = [["pull", "--ignore-buildable"], ["build", "--pull"]]
    elif action == "up":
        steps = [["up", "-d"]]
    else:
        steps = [[action]]

    parent = _helper_parent(ctx)
    if ctx is not None and parent is not None:
        result = _run_in_helper(
            compose_path, steps, project_name=project_name, ctx=ctx, parent=parent
        )
        return {
            "action": action,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }

    stdout: list[str] = []
    stderr: list[str] = []
    exit_code = 0
    for args in steps:
        result = _compose(compose_path, args, project_name=project_name, timeout=_timeout(args))
        stdout.append(result.stdout)
        stderr.append(result.stderr)
        exit_code = result.returncode
        if exit_code != 0:
            break

    return {
        "action": action,
        "exit_code": exit_code,
        "stdout": "".join(stdout),
        "stderr": "".join(stderr),
    }


def check(step: str, exit_code: int, stdout: str, stderr: str) -> None:
    """Raise ComposeError when `docker compose <step>` failed."""
    if exit_code != 0:
        detail = (stderr or stdout or "").strip()[-1000:]
        raise ComposeError(f"`docker compose {step}` failed (exit {exit_code}): {detail}")


def joined_output(stdout: str, stderr: str) -> str:
    # docker compose writes its progress to stderr, so keep both streams.
    return "\n".join(text for text in (stdout, stderr) if text)


def _run_one(
    compose_path: Path, args: list[str], *, project_name: str | None, ctx: JobContext | None
) -> subprocess.CompletedProcess[str]:
    parent = _helper_parent(ctx)
    if ctx is not None and parent is not None:
        return _run_in_helper(
            compose_path, [args], project_name=project_name, ctx=ctx, parent=parent
        )
    return _compose(compose_path, args, project_name=project_name)


def down(
    compose_path: Path,
    *,
    remove_volumes: bool = False,
    project_name: str | None = None,
    ctx: JobContext | None = None,
) -> str:
    """`docker compose down`, with `-v` to remove the stack's named volumes too.
    Returns the command output; raises ComposeError when it fails."""
    args = ["down", "--remove-orphans", *(["--volumes"] if remove_volumes else [])]
    result = _run_one(compose_path, args, project_name=project_name, ctx=ctx)
    check("down", result.returncode, result.stdout, result.stderr)
    return joined_output(result.stdout, result.stderr)


def pull_service(compose_path: Path, service: str, *, project_name: str | None = None) -> None:
    """Pull the image of one service. A service with `build:` is left to `build_service`."""
    result = _compose(
        compose_path,
        ["pull", "--ignore-buildable", service],
        project_name=project_name,
        timeout=PULL_TIMEOUT,
    )
    check("pull", result.returncode, result.stdout, result.stderr)


def build_service(compose_path: Path, service: str, *, project_name: str | None = None) -> None:
    """Rebuild one service on a fresh base image; a no-op for a service without `build:`.

    A git build context is fetched again, so a new commit on its ref goes in.
    """
    result = _compose(
        compose_path, ["build", "--pull", service], project_name=project_name, timeout=PULL_TIMEOUT
    )
    check("build", result.returncode, result.stdout, result.stderr)


def recreate_service(
    compose_path: Path,
    service: str,
    *,
    project_name: str | None = None,
    ctx: JobContext | None = None,
) -> None:
    """Recreate one service on its current image, leaving the rest of the stack alone."""
    args = ["up", "-d", "--no-deps", service]
    result = _run_one(compose_path, args, project_name=project_name, ctx=ctx)
    check("up", result.returncode, result.stdout, result.stderr)


def stream_logs(
    compose_path: Path, *, tail: int = 200, project_name: str | None = None
) -> subprocess.Popen[bytes]:
    """Follow the aggregated logs of a Compose project.

    Returns the running process; the caller owns it and must terminate it when
    the client goes away.
    """
    command = _command(
        compose_path, ["logs", "--follow", "--no-color", "--tail", str(tail)], project_name
    )
    logger.info("Streaming: %s", " ".join(command))
    try:
        return subprocess.Popen(  # noqa: S603 - args list, no shell
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            cwd=host_path_service.to_host(compose_path).parent,
        )
    except FileNotFoundError as exc:
        raise ComposeError("`docker` CLI not found on PATH") from exc
