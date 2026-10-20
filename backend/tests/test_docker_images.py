"""docker_service image helpers, against a fake Docker client."""

from types import SimpleNamespace
from typing import Any, NoReturn

import pytest
from docker.errors import APIError, DockerException
from docker.errors import ImageNotFound as DockerImageNotFound

from app.services import docker_service

NGINX_ID = "sha256:nginx"
OLD_ID = "sha256:old"


def _image(
    image_id: str, tags: list[str], size: int = 0, created: str = "2026-01-02T03:04:05.123456789Z"
) -> SimpleNamespace:
    return SimpleNamespace(id=image_id, tags=tags, attrs={"Size": size, "Created": created})


def _container(name: str, image_id: str, status: str = "running") -> SimpleNamespace:
    return SimpleNamespace(name=name, status=status, attrs={"Image": image_id})


def _api_error(status_code: int, explanation: str = "conflict") -> APIError:
    return APIError(
        "error",
        response=SimpleNamespace(status_code=status_code, url="http://docker/images", reason="x"),
        explanation=explanation,
    )


class FakeImages:
    def __init__(self, images: list[SimpleNamespace]) -> None:
        self.images = images
        self.removed: list[tuple[str, bool]] = []
        self.remove_error: Exception | None = None
        self.prune_filters: dict[str, bool] | None = None
        self.prune_result: dict[str, Any] = {}

    def list(self) -> list[SimpleNamespace]:
        return list(self.images)

    def get(self, reference: str) -> SimpleNamespace:
        for image in self.images:
            if reference in image.tags or reference == image.id:
                return image
        raise DockerImageNotFound(f"No such image: {reference}")

    def remove(self, reference: str, force: bool = False) -> None:
        if self.remove_error:
            raise self.remove_error
        self.removed.append((reference, force))

    def prune(self, filters: dict[str, bool] | None = None) -> dict[str, Any]:
        self.prune_filters = filters
        return self.prune_result


class FakeContainers:
    def __init__(self, containers: list[SimpleNamespace]) -> None:
        self.containers = containers

    def list(self, all: bool = False) -> list[SimpleNamespace]:
        return [container for container in self.containers if all or container.status == "running"]


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    client = SimpleNamespace(
        images=FakeImages(
            [
                _image(NGINX_ID, ["nginx:latest", "nginx:1.27"], size=1024),
                _image(OLD_ID, ["alpine:3.18"], size=2048),
                _image("sha256:dangling", [], size=10),
            ]
        ),
        containers=FakeContainers(
            [
                _container("web", NGINX_ID, "running"),
                _container("job", OLD_ID, "exited"),
            ]
        ),
    )
    monkeypatch.setattr(docker_service, "_client", lambda: client)
    return client


# --- list_images --------------------------------------------------------------


def test_list_images_maps_fields_and_usage(fake: SimpleNamespace) -> None:
    images = {
        (image.tags[0] if image.tags else image.id): image for image in docker_service.list_images()
    }

    nginx = images["nginx:latest"]
    assert nginx.id == NGINX_ID
    assert nginx.tags == ["nginx:latest", "nginx:1.27"]
    assert nginx.size == 1024
    assert nginx.created_at is not None and nginx.created_at.year == 2026
    assert [(container.name, container.running) for container in nginx.used_by] == [("web", True)]

    # Stopped containers still count as users.
    alpine_users = images["alpine:3.18"].used_by
    assert [(container.name, container.running) for container in alpine_users] == [("job", False)]
    assert images["sha256:dangling"].used_by == []


def test_list_images_sorts_by_tag_with_untagged_last(fake: SimpleNamespace) -> None:
    order = [image.tags[0] if image.tags else None for image in docker_service.list_images()]
    assert order == ["alpine:3.18", "nginx:latest", None]


def test_list_images_handles_missing_created(fake: SimpleNamespace) -> None:
    fake.images.images = [SimpleNamespace(id="sha256:x", tags=["x:1"], attrs={})]
    [image] = docker_service.list_images()
    assert image.created_at is None
    assert image.size == 0


def test_list_images_docker_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom() -> NoReturn:
        raise DockerException("socket gone")

    client = SimpleNamespace(images=SimpleNamespace(list=boom), containers=FakeContainers([]))
    monkeypatch.setattr(docker_service, "_client", lambda: client)
    with pytest.raises(docker_service.DockerUnavailable):
        docker_service.list_images()


# --- remove_image -------------------------------------------------------------


def test_remove_unused_image(fake: SimpleNamespace) -> None:
    fake.containers.containers = []
    docker_service.remove_image("alpine:3.18")
    assert fake.images.removed == [("alpine:3.18", False)]


def test_remove_passes_force(fake: SimpleNamespace) -> None:
    docker_service.remove_image("alpine:3.18", force=True)
    assert fake.images.removed == [("alpine:3.18", True)]


def test_remove_missing_image(fake: SimpleNamespace) -> None:
    with pytest.raises(docker_service.ImageNotFound):
        docker_service.remove_image("ghost:1")
    assert fake.images.removed == []


@pytest.mark.parametrize("force", [False, True])
def test_remove_refuses_running_image_even_with_force(fake: SimpleNamespace, force: bool) -> None:
    with pytest.raises(docker_service.ImageInUse, match="web"):
        docker_service.remove_image("nginx:1.27", force=force)
    assert fake.images.removed == []


def test_remove_conflict_from_docker_is_in_use(fake: SimpleNamespace) -> None:
    fake.images.remove_error = _api_error(409, "image is being used by stopped container")
    with pytest.raises(docker_service.ImageInUse, match="stopped container"):
        docker_service.remove_image("alpine:3.18")


def test_remove_other_api_error_is_unavailable(fake: SimpleNamespace) -> None:
    fake.images.remove_error = _api_error(500, "daemon exploded")
    with pytest.raises(docker_service.DockerUnavailable):
        docker_service.remove_image("alpine:3.18")


def test_remove_race_where_image_vanishes(fake: SimpleNamespace) -> None:
    fake.images.remove_error = DockerImageNotFound("gone")
    with pytest.raises(docker_service.ImageNotFound):
        docker_service.remove_image("alpine:3.18")


# --- prune_images -------------------------------------------------------------


def test_prune_removes_tagged_images_too(fake: SimpleNamespace) -> None:
    docker_service.prune_images()
    assert fake.images.prune_filters == {"dangling": False}


def test_prune_counts_deleted_layers_not_untags(fake: SimpleNamespace) -> None:
    fake.images.prune_result = {
        "ImagesDeleted": [
            {"Untagged": "alpine:3.18"},
            {"Deleted": "sha256:aaa"},
            {"Deleted": "sha256:bbb"},
        ],
        "SpaceReclaimed": 4096,
    }
    result = docker_service.prune_images()
    assert result.deleted == ["sha256:aaa", "sha256:bbb"]
    assert result.space_reclaimed == 4096


def test_prune_nothing_to_do(fake: SimpleNamespace) -> None:
    # Docker sends null rather than [] when nothing was removed.
    fake.images.prune_result = {"ImagesDeleted": None, "SpaceReclaimed": 0}
    result = docker_service.prune_images()
    assert result.deleted == []
    assert result.space_reclaimed == 0


def test_prune_docker_down(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(filters: dict[str, bool] | None = None) -> NoReturn:
        raise DockerException("socket gone")

    client = SimpleNamespace(images=SimpleNamespace(prune=boom))
    monkeypatch.setattr(docker_service, "_client", lambda: client)
    with pytest.raises(docker_service.DockerUnavailable):
        docker_service.prune_images()
