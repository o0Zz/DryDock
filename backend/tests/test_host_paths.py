"""Repo host-path alias, so relative bind mounts in Compose files resolve on the host."""

import subprocess
from pathlib import Path
from typing import Any, NoReturn

import pytest

from app.core.config import settings
from app.services import compose_service, docker_service, host_path_service

CONTAINER_ID = "a" * 64


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repo"
    (repo / "web").mkdir(parents=True)
    monkeypatch.setattr(settings, "repo_path", repo)
    monkeypatch.setattr(settings, "repo_host_path", None)
    monkeypatch.setattr(host_path_service, "_alias", None)
    return repo


@pytest.fixture
def can_symlink(tmp_path: Path) -> None:
    # Windows needs developer mode or admin rights for symlinks.
    try:
        (tmp_path / "probe").symlink_to(tmp_path, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks not available on this machine")


def _mountinfo(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str) -> None:
    path = tmp_path / "mountinfo"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(host_path_service, "MOUNTINFO", path)


# --- to_host ------------------------------------------------------------------


def test_to_host_without_alias_is_identity(repo: Path) -> None:
    path = repo / "web" / "docker-compose.yml"
    assert host_path_service.to_host(path) == path


def test_to_host_maps_repo_paths_only(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    alias = tmp_path / "home" / "pi" / "docker"
    monkeypatch.setattr(host_path_service, "_alias", alias)

    assert host_path_service.to_host(repo / "web" / "compose.yml") == alias / "web" / "compose.yml"
    outside = tmp_path / "elsewhere" / "compose.yml"
    assert host_path_service.to_host(outside) == outside


# --- detection ------------------------------------------------------------------


def test_detect_uses_container_id_from_mountinfo(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mountinfo(
        monkeypatch,
        tmp_path,
        f"1 2 8:1 /var/lib/docker/containers/{CONTAINER_ID}/hostname /etc/hostname rw"
        " - ext4 /dev/sda1\n",
    )
    calls: list[tuple[str, str]] = []

    def mount_source(container_id: str, destination: str) -> str:
        calls.append((container_id, destination))
        return "/home/pi/docker"

    monkeypatch.setattr(docker_service, "mount_source", mount_source)

    assert host_path_service.detect_host_path() == Path("/home/pi/docker")
    assert calls == [(CONTAINER_ID, repo.as_posix())]


def test_detect_falls_back_to_hostname(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _mountinfo(monkeypatch, tmp_path, "1 2 8:1 / / rw - overlay overlay\n")
    monkeypatch.setattr(host_path_service.socket, "gethostname", lambda: "abc123")
    seen: list[str] = []
    monkeypatch.setattr(
        docker_service,
        "mount_source",
        lambda container_id, destination: seen.append(container_id) or None,
    )

    assert host_path_service.detect_host_path() is None
    assert seen == ["abc123"]


def test_detect_outside_a_container(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(host_path_service, "MOUNTINFO", tmp_path / "missing")
    assert host_path_service.detect_host_path() is None


def test_explicit_setting_wins(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "repo_host_path", Path("/srv/stacks"))
    monkeypatch.setattr(
        docker_service, "mount_source", lambda *args: pytest.fail("should not inspect")
    )
    assert host_path_service.detect_host_path() == Path("/srv/stacks")


# --- setup ------------------------------------------------------------------------


def _host(monkeypatch: pytest.MonkeyPatch, host: Path | None) -> None:
    monkeypatch.setattr(host_path_service, "detect_host_path", lambda: host)


def test_setup_creates_alias(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, can_symlink: None
) -> None:
    host = tmp_path / "home" / "pi" / "docker"
    _host(monkeypatch, host)

    assert host_path_service.setup() == host
    assert host.is_symlink()
    assert (host / "web").is_dir()  # the repo is readable through it
    assert host_path_service.to_host(repo / "web" / "c.yml") == host / "web" / "c.yml"

    # Restarting finds the existing link and reuses it.
    assert host_path_service.setup() == host


def test_setup_not_needed(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _host(monkeypatch, None)
    assert host_path_service.setup() is None

    _host(monkeypatch, repo)  # mounted at the same path as on the host
    assert host_path_service.setup() is None
    assert host_path_service.to_host(repo / "web") == repo / "web"


def test_setup_refuses_host_path_inside_repo(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _host(monkeypatch, repo / "web")
    assert host_path_service.setup() is None


def test_setup_leaves_unrelated_existing_path_alone(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    host = tmp_path / "taken"
    host.mkdir()
    _host(monkeypatch, host)

    assert host_path_service.setup() is None
    assert not host.is_symlink()


def test_setup_leaves_foreign_symlink_alone(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, can_symlink: None
) -> None:
    other = tmp_path / "other"
    other.mkdir()
    host = tmp_path / "link"
    host.symlink_to(other, target_is_directory=True)
    _host(monkeypatch, host)

    assert host_path_service.setup() is None


def test_setup_survives_docker_down(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def down() -> NoReturn:
        raise docker_service.DockerUnavailable("down")

    monkeypatch.setattr(host_path_service, "detect_host_path", down)
    assert host_path_service.setup() is None


# --- compose runs through the alias ---------------------------------------------------


def test_compose_commands_use_host_path(
    repo: Path, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    alias = tmp_path / "home" / "pi" / "docker"
    monkeypatch.setattr(host_path_service, "_alias", alias)
    calls: list[tuple[list[str], Path]] = []

    def fake_run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        calls.append((command, kwargs["cwd"]))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(compose_service.subprocess, "run", fake_run)

    compose_service.recreate_service(repo / "web" / "docker-compose.yml", "nginx")
    compose_service.run_action(repo / "web" / "docker-compose.yml", "up")

    for command, cwd in calls:
        assert command[3] == str(alias / "web" / "docker-compose.yml")
        assert cwd == alias / "web"


# --- mount_source -------------------------------------------------------------------


def test_mount_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from docker.errors import NotFound

    def get(container_id: str) -> SimpleNamespace:
        if container_id != CONTAINER_ID:
            raise NotFound("missing")
        return SimpleNamespace(
            attrs={
                "Mounts": [
                    {"Destination": "/data", "Source": "/var/lib/docker/volumes/d/_data"},
                    {"Destination": "/repo", "Source": "/home/pi/docker"},
                ]
            }
        )

    client = SimpleNamespace(containers=SimpleNamespace(get=get))
    monkeypatch.setattr(docker_service, "_client", lambda: client)

    assert docker_service.mount_source(CONTAINER_ID, "/repo") == "/home/pi/docker"
    assert docker_service.mount_source(CONTAINER_ID, "/nope") is None
    assert docker_service.mount_source("other", "/repo") is None
