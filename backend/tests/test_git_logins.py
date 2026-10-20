"""Git logins: storage, the update check, build secrets, and the repo's commit/push/pull."""

import base64
import shutil
import subprocess
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from fastapi.testclient import TestClient

from app.core.config import settings
from app.services import compose_service, git_auth_service, git_service, repo_git_service

REPO = "https://git.example.com/me/app.git"


@pytest.fixture(autouse=True)
def data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(settings, "data_path", tmp_path / "data")
    return tmp_path / "data"


# --- storage ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "host"),
    [
        (REPO, "git.example.com"),
        ("git.example.com", "git.example.com"),
        ("Git.Example.com:3000", "git.example.com:3000"),
        ("https://user:pw@git.example.com:3000/me/app.git", "git.example.com:3000"),
        ("git@github.com:me/app.git", "github.com"),
    ],
)
def test_normalize(value: str, host: str) -> None:
    assert git_auth_service.normalize(value) == host


def test_store_list_and_remove(data: Path) -> None:
    assert git_auth_service.set_credentials(REPO, "me", "p@ss:word") == "git.example.com"
    git_auth_service.set_credentials("github.com", "octo", "ghp_x")

    assert git_auth_service.list_hosts() == [("git.example.com", "me"), ("github.com", "octo")]
    assert git_auth_service.credentials("https://git.example.com/other.git") == ("me", "p@ss:word")
    # git's own credential store format, with the special characters escaped.
    store = (data / "git" / "credentials").read_text(encoding="utf-8")
    assert "https://me:p%40ss%3Aword@git.example.com\n" in store
    header = git_auth_service.header_path("git.example.com").read_text(encoding="utf-8")
    assert header == "Basic " + base64.b64encode(b"me:p@ss:word").decode()

    assert git_auth_service.remove_credentials("git.example.com")
    assert not git_auth_service.remove_credentials("git.example.com")
    assert not git_auth_service.header_path("git.example.com").exists()
    assert git_auth_service.list_hosts() == [("github.com", "octo")]


def test_git_env_only_for_https_hosts_with_a_login() -> None:
    git_auth_service.set_credentials(REPO, "me", "tok")
    env = git_auth_service.git_env(REPO)
    assert env["GIT_CONFIG_KEY_0"] == "http.https://git.example.com/.extraheader"
    assert env["GIT_CONFIG_VALUE_0"] == "Authorization: " + git_auth_service.auth_header(REPO)
    assert git_auth_service.git_env("https://github.com/me/app.git") == {}
    assert git_auth_service.git_env("git@git.example.com:me/app.git") == {}


# --- update check ---------------------------------------------------------------------


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {"status": 200, "auth": []}

    def get(url: str, **kwargs: Any) -> httpx.Response:
        state["auth"].append(kwargs.get("auth"))
        return httpx.Response(state["status"], content=b"0000")

    monkeypatch.setattr(git_service.httpx, "get", get)
    return state


def test_list_refs_sends_the_stored_login(server: dict[str, Any]) -> None:
    git_service.list_refs(REPO)
    git_auth_service.set_credentials(REPO, "me", "tok")
    git_service.list_refs(REPO)
    git_service.list_refs(REPO, auth=("other", "x"))
    assert server["auth"] == [None, ("me", "tok"), ("other", "x")]


def test_list_refs_errors_say_what_to_do(server: dict[str, Any]) -> None:
    server["status"] = 401
    with pytest.raises(git_service.GitError, match="add one for git.example.com in Settings"):
        git_service.list_refs(REPO)
    git_auth_service.set_credentials(REPO, "me", "tok")
    with pytest.raises(git_service.GitError, match="refused the login"):
        git_service.list_refs(REPO)


def test_add_login_checks_a_repo_url(client: TestClient, server: dict[str, Any]) -> None:
    server["status"] = 403
    response = client.post(
        "/api/git/credentials", json={"url": REPO, "username": "me", "token": "bad"}
    )
    assert response.status_code == 400
    assert git_auth_service.list_hosts() == []

    server["status"] = 200
    response = client.post(
        "/api/git/credentials", json={"url": REPO, "username": "me", "token": "good"}
    )
    assert response.status_code == 201
    assert response.json() == {"host": "git.example.com", "username": "me"}
    # A bare host cannot be checked: it is stored as is.
    response = client.post(
        "/api/git/credentials", json={"url": "github.com", "username": "octo", "token": "t"}
    )
    assert response.status_code == 201
    assert server["auth"] == [("me", "bad"), ("me", "good")]
    assert [row["host"] for row in client.get("/api/git/credentials").json()] == [
        "git.example.com",
        "github.com",
    ]
    assert client.delete("/api/git/credentials", params={"host": "github.com"}).status_code == 204
    assert client.delete("/api/git/credentials", params={"host": "github.com"}).status_code == 404


# --- build secrets --------------------------------------------------------------------


def _stack(tmp_path: Path, services: dict[str, Any]) -> Path:
    path = tmp_path / "stack" / "docker-compose.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"services": services}), encoding="utf-8")
    return path


def test_secrets_file_covers_git_builds_with_a_login(tmp_path: Path) -> None:
    compose = _stack(
        tmp_path,
        {
            "app": {"build": f"{REPO}#main"},
            "worker": {"build": {"context": f"{REPO}#main:worker"}},
            "public": {"build": "https://github.com/me/tool.git"},
            "local": {"build": "."},
            "db": {"image": "postgres:16"},
        },
    )
    assert compose_service.git_secrets_file([compose]) is None

    git_auth_service.set_credentials(REPO, "me", "tok")
    path = compose_service.git_secrets_file([compose])
    assert path is not None
    header = git_auth_service.header_path("git.example.com").as_posix()
    secret = [{"source": "drydock_git_0", "target": "GIT_AUTH_HEADER.git.example.com"}]
    assert yaml.safe_load(path.read_text(encoding="utf-8")) == {
        "secrets": {"drydock_git_0": {"file": header}},
        "services": {
            "app": {"build": {"secrets": secret}},
            "worker": {"build": {"secrets": secret}},
        },
    }

    command = compose_service._command(compose, ["build"])
    assert command[-3:] == ["-f", str(path), "build"]


# --- commit, push, pull ---------------------------------------------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def checkout(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """A clone of a bare remote, with the Compose folder at `docker/` inside it."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(remote))
    root = tmp_path / "checkout"
    _git(tmp_path, "clone", "-q", str(remote), str(root))
    _git(root, "config", "user.name", "Host User")
    _git(root, "config", "user.email", "host@example.com")
    (root / "docker" / "web").mkdir(parents=True)
    (root / "docker" / "web" / "docker-compose.yml").write_text("services: {}\n")
    (root / "README.md").write_text("hi\n")
    _git(root, "add", ".")
    _git(root, "commit", "-q", "-m", "init")
    _git(root, "push", "-q", "-u", "origin", "main")
    monkeypatch.setattr(settings, "repo_path", root / "docker")
    return root


def test_status_outside_a_repo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "repo_path", tmp_path)
    monkeypatch.setattr(repo_git_service.shutil, "which", lambda name: "/usr/bin/git")
    state = repo_git_service.status()
    assert not state.supported
    assert "not in a git repository" in (state.reason or "")


@needs_git
def test_commit_covers_only_the_repo_folder_and_pushes(checkout: Path) -> None:
    (checkout / "docker" / "web" / "docker-compose.yml").write_text("services: {a: {}}\n")
    (checkout / "docker" / "new.yml").write_text("services: {}\n")
    (checkout / "README.md").write_text("changed outside the repo folder\n")

    state = repo_git_service.status()
    assert state.supported
    assert (state.branch, state.upstream, state.ahead) == ("main", "origin/main", 0)
    assert sorted((change.status, change.path) for change in state.changes) == [
        (" M", "web/docker-compose.yml"),
        ("??", "new.yml"),
    ]

    repo_git_service.commit("Update web", "alice")
    assert repo_git_service.status().ahead == 1
    # The repo's own identity wins over the DryDock user.
    assert _git(checkout, "log", "-1", "--format=%an %s") == "Host User Update web"
    assert _git(checkout, "status", "--porcelain") == "M README.md"

    repo_git_service.push()
    assert repo_git_service.status().ahead == 0


@needs_git
def test_pull_fast_forwards(checkout: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    _git(tmp_path, "clone", "-q", str(tmp_path / "remote.git"), str(other))
    (other / "docker" / "web" / "docker-compose.yml").write_text("services: {b: {}}\n")
    _git(other, "-c", "user.name=x", "-c", "user.email=x@x", "commit", "-qam", "remote edit")
    _git(other, "push", "-q")

    repo_git_service.pull()
    compose = checkout / "docker" / "web" / "docker-compose.yml"
    assert compose.read_text() == "services: {b: {}}\n"


@needs_git
def test_repo_routes(client: TestClient, checkout: Path) -> None:
    body = client.get("/api/git/repo").json()
    assert body["supported"] and body["branch"] == "main" and body["changes"] == []
    assert client.post("/api/git/repo/merge").status_code == 422
