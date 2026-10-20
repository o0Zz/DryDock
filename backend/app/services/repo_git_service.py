"""Commit, push and pull the repo folder, when it is part of a git repository.

The git repo may be bigger than the Compose folder: mount its root and point
`DRYDOCK_REPO_PATH` at the folder inside it (`/repo/docker`). Commits and the
change list only cover that folder.

DryDock runs as root, but the repo belongs to someone on the host. git runs as
the owner of `.git`, so the objects and files it writes stay theirs, and git's
"dubious ownership" check passes. Pushes and pulls use the stored login for the
remote's host (git_auth_service). The host's global git config is not visible
here, so a repo without `user.name` commits as the DryDock user.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from app.core.config import settings
from app.services import git_auth_service

logger = logging.getLogger(__name__)

# Push and pull go over the network; a Pi on a slow link takes a while.
NETWORK_TIMEOUT = 300
LOCAL_TIMEOUT = 60

class RepoGitError(Exception):
    """git is missing, the folder is not a repo, or a git command failed."""


@dataclass
class Change:
    # Two-letter `git status --porcelain` code: index, then work tree ("M ", "??").
    status: str
    # Relative to the repo folder.
    path: str


@dataclass
class RepoStatus:
    supported: bool
    # Why not, when not supported.
    reason: str | None = None
    branch: str | None = None
    upstream: str | None = None
    # Against the upstream as of the last fetch or pull.
    ahead: int = 0
    behind: int = 0
    # Without any login in it.
    remote_url: str | None = None
    has_login: bool = False
    changes: list[Change] = field(default_factory=list)


def _git_root() -> Path | None:
    """The folder holding `.git`, the repo folder or one of its parents."""
    for folder in (settings.repo_path, *settings.repo_path.parents):
        if (folder / ".git").exists():
            return folder
    return None


def _run(
    args: list[str],
    *,
    root: Path,
    extra_env: dict[str, str] | None = None,
    timeout: int = LOCAL_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "LC_ALL": "C",
        **(extra_env or {}),
    }
    kwargs: dict[str, object] = {}
    owner = (root / ".git").stat()
    if hasattr(os, "geteuid") and os.geteuid() == 0 and owner.st_uid != 0:
        kwargs = {"user": owner.st_uid, "group": owner.st_gid, "extra_groups": []}
        # root's home is not readable by that user, and git dies on an unreadable config.
        env["HOME"] = tempfile.gettempdir()
    try:
        return subprocess.run(  # noqa: S603 - args list, no shell
            ["git", *args],
            cwd=settings.repo_path,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
            **kwargs,  # type: ignore[arg-type]
        )
    except FileNotFoundError as exc:
        raise RepoGitError("git is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise RepoGitError(f"`git {args[0]}` timed out after {timeout}s") from exc


def _check(result: subprocess.CompletedProcess[str], step: str) -> str:
    output = "\n".join(text.strip() for text in (result.stdout, result.stderr) if text.strip())
    if result.returncode != 0:
        raise RepoGitError(f"`git {step}` failed (exit {result.returncode}): {output[-1000:]}")
    return output


def _root_or_raise() -> Path:
    if shutil.which("git") is None:
        raise RepoGitError("git is not installed")
    root = _git_root()
    if root is None:
        raise RepoGitError(f"{settings.repo_path} is not in a git repository")
    return root


def _strip_login(url: str) -> str:
    parts = urlsplit(url)
    if not parts.username and not parts.password:
        return url
    netloc = parts.hostname or ""
    if parts.port:
        netloc += f":{parts.port}"
    return urlunsplit(parts._replace(netloc=netloc))


def _remote_url(root: Path, upstream: str | None) -> str | None:
    remote = upstream.split("/", 1)[0] if upstream else "origin"
    result = _run(["remote", "get-url", remote], root=root)
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _parse_branch(line: str, state: RepoStatus) -> None:
    """Read `## main...origin/main [ahead 1, behind 2]`, `## No commits yet on main`
    or `## HEAD (no branch)`."""
    line = line.removeprefix("## ").removeprefix("No commits yet on ")
    line, _, track = line.partition(" [")
    branch, _, upstream = line.partition("...")
    if branch.startswith("HEAD (no branch)"):
        return
    state.branch = branch
    state.upstream = upstream or None
    for part in track.rstrip("]").split(","):
        word, _, number = part.strip().partition(" ")
        if word == "ahead" and number.isdigit():
            state.ahead = int(number)
        elif word == "behind" and number.isdigit():
            state.behind = int(number)


def status() -> RepoStatus:
    try:
        root = _root_or_raise()
    except RepoGitError as exc:
        return RepoStatus(supported=False, reason=str(exc))
    # `-- .` from the repo folder: only its changes, with paths relative to it.
    result = _run(
        ["status", "--porcelain=v1", "-z", "--branch", "--untracked-files=all", "--", "."],
        root=root,
    )
    _check(result, "status")
    prefix = _run(["rev-parse", "--show-prefix"], root=root).stdout.strip()
    entries = result.stdout.split("\0")
    state = RepoStatus(supported=True)
    if entries and entries[0].startswith("## "):
        _parse_branch(entries.pop(0), state)
    entries = iter(entries)
    for entry in entries:
        if len(entry) < 4:
            continue
        code, path = entry[:2], entry[3:]
        if code[0] in "RC":
            next(entries, None)  # the old path of a rename or copy
        state.changes.append(Change(status=code, path=path.removeprefix(prefix)))
    remote = _remote_url(root, state.upstream)
    if remote:
        state.remote_url = _strip_login(remote)
        state.has_login = git_auth_service.credentials(remote) is not None
    return state


def _identity(root: Path, username: str) -> list[str]:
    """`-c` options for the author, unless the repo sets its own."""
    configured = _run(["config", "user.name"], root=root).stdout.strip()
    if configured:
        return []
    return ["-c", f"user.name={username}", "-c", f"user.email={username}@drydock.local"]


def _network_env(root: Path) -> dict[str, str]:
    """The login for the remote that `push` and `pull` talk to."""
    upstream = _run(["rev-parse", "--abbrev-ref", "@{upstream}"], root=root)
    remote = _remote_url(root, upstream.stdout.strip() if upstream.returncode == 0 else None)
    return git_auth_service.git_env(remote) if remote else {}


def commit(message: str, username: str) -> str:
    """Commit every change in the repo folder. Returns git's output."""
    root = _root_or_raise()
    _check(_run(["add", "--all", "--", "."], root=root), "add")
    # `-- .` commits only the repo folder, even if other files are staged.
    result = _run([*_identity(root, username), "commit", "-m", message, "--", "."], root=root)
    return _check(result, "commit")


def push() -> str:
    root = _root_or_raise()
    result = _run(["push"], root=root, extra_env=_network_env(root), timeout=NETWORK_TIMEOUT)
    return _check(result, "push")


def pull() -> str:
    """Fast-forward only: a merge or rebase belongs on the host, where conflicts can be fixed."""
    root = _root_or_raise()
    result = _run(
        ["pull", "--ff-only"], root=root, extra_env=_network_env(root), timeout=NETWORK_TIMEOUT
    )
    return _check(result, "pull")
