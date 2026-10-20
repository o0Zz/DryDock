"""Browsing and downloading volume files, with the Docker client faked."""

import io
import tarfile
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any

import pytest
from docker.errors import NotFound
from fastapi.testclient import TestClient

from app.core.security import get_current_user
from app.main import app
from app.schemas.volume import VolumeEntry
from app.services import docker_service, volume_files_service


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("", "/"), ("/", "/"), ("a/b/", "/a/b"), ("//a//b", "/a/b"), ("../../etc", "/etc")],
)
def test_normalize_stays_inside_the_volume(raw: str, expected: str) -> None:
    assert volume_files_service.normalize(raw) == expected


def test_parse_entries() -> None:
    output = (
        b"41ed 4096 1700000000 /volume/sub\n"
        b"81a4 11 1700000000 /volume/a file.txt\n"
        b"a1ff 11 1700000000 /volume/link\n"
        b"81a4 1 1700000000 /volume/bad\n"
        b"name\n"  # tail of a name that holds a newline
    )

    entries = docker_service._parse_entries(output)

    assert [(entry.name, entry.type, entry.size) for entry in entries] == [
        ("sub", "dir", 4096),
        ("a file.txt", "file", 11),
        ("link", "link", 11),
        ("bad", "file", 1),
    ]


def test_list_dir_sorts_folders_first_and_truncates(monkeypatch: pytest.MonkeyPatch) -> None:
    entries = [
        VolumeEntry(name="b", type="file", size=1),
        VolumeEntry(name="Z", type="dir", size=1),
        VolumeEntry(name="a", type="file", size=1),
    ]
    monkeypatch.setattr(volume_files_service, "_image", "helper")
    monkeypatch.setattr(docker_service, "list_volume_dir", lambda *args, **kwargs: entries)
    monkeypatch.setattr(volume_files_service, "MAX_ENTRIES", 2)

    listing = volume_files_service.list_dir("data", "x/../")

    assert listing.path == "/"
    assert [entry.name for entry in listing.entries] == ["Z", "a"]
    assert listing.truncated


def _tar_chunks(name: str, content: bytes) -> Iterator[bytes]:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        tar.addfile(info, io.BytesIO(content))
    data = buffer.getvalue()
    # Small, uneven chunks to exercise the reader's buffering.
    return iter(data[start : start + 100] for start in range(0, len(data), 100))


class _FakeHelper:
    def __init__(self, archive: Any) -> None:
        self.archive = archive
        self.removed = False

    def get_archive(self, path: str, chunk_size: int) -> Any:
        if isinstance(self.archive, Exception):
            raise self.archive
        return self.archive

    def remove(self, force: bool = False) -> None:
        self.removed = True


def _fake_client(monkeypatch: pytest.MonkeyPatch, helper: _FakeHelper) -> None:
    client = SimpleNamespace(
        containers=SimpleNamespace(create=lambda **kwargs: helper),
        volumes=SimpleNamespace(get=lambda name: SimpleNamespace(name=name)),
    )
    monkeypatch.setattr(docker_service, "_client", lambda: client)


def test_open_file_streams_then_removes_the_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    content = bytes(range(256)) * 10
    helper = _FakeHelper(
        (
            _tar_chunks("blob.bin", content),
            {"name": "blob.bin", "size": len(content), "mode": 0o644},
        )
    )
    _fake_client(monkeypatch, helper)

    file = docker_service.open_volume_file("data", "/dir/blob.bin", image="helper")

    assert (file.name, file.size) == ("blob.bin", len(content))
    assert not helper.removed
    assert b"".join(file.chunks) == content
    assert helper.removed


@pytest.mark.parametrize(
    ("archive", "error"),
    [
        ((iter([]), {"size": 4096, "mode": 1 << 31}), docker_service.NotAFile),
        ((iter([]), {"size": 11, "mode": (1 << 27) | 0o777}), docker_service.NotAFile),
        (NotFound("missing"), docker_service.DockerNotFound),
    ],
)
def test_open_file_errors_remove_the_helper(
    monkeypatch: pytest.MonkeyPatch, archive: Any, error: type[Exception]
) -> None:
    helper = _FakeHelper(archive)
    _fake_client(monkeypatch, helper)

    with pytest.raises(error):
        docker_service.open_volume_file("data", "/x", image="helper")
    assert helper.removed


def test_download_sends_an_attachment(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    file = docker_service.VolumeFile(name="my file.txt", size=5, chunks=iter([b"he", b"llo"]))
    monkeypatch.setattr(volume_files_service, "open_file", lambda volume, path: file)

    response = client.get("/api/volumes/data/files/download", params={"path": "/my file.txt"})

    assert response.status_code == 200
    assert response.content == b"hello"
    assert response.headers["content-length"] == "5"
    assert response.headers["content-disposition"] == "attachment; filename*=UTF-8''my%20file.txt"


def test_not_a_file_is_a_bad_request(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def open_file(volume: str, path: str) -> None:
        raise docker_service.NotAFile(f"{path} is not a regular file")

    monkeypatch.setattr(volume_files_service, "open_file", open_file)

    response = client.get("/api/volumes/data/files/download", params={"path": "/sub"})

    assert response.status_code == 400
    assert response.json() == {"detail": "/sub is not a regular file"}


def test_files_are_admin_only() -> None:
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=2, is_admin=False)
    try:
        user = TestClient(app)
        assert user.get("/api/volumes/data/files").status_code == 403
        assert (
            user.get("/api/volumes/data/files/download", params={"path": "/a"}).status_code == 403
        )
    finally:
        app.dependency_overrides.clear()
