"""docker_service image helpers, against a fake Docker client."""

from types import SimpleNamespace

import pytest
from docker.errors import APIError, DockerException
from docker.errors import ImageNotFound as DockerImageNotFound

from app.services import docker_service

NGINX_ID = "sha256:nginx"
OLD_ID = "sha256:old"


def _image(image_id, tags, size=0, created="2026-01-02T03:04:05.123456789Z"):
    return SimpleNamespace(id=image_id, tags=tags, attrs={"Size": size, "Created": created})


def _container(name, image_id, status="running"):
    return SimpleNamespace(name=name, status=status, attrs={"Image": image_id})


def _api_error(code, explanation="conflict"):
    return APIError(
        "error",
        response=SimpleNamespace(status_code=code, url="http://docker/images", reason="x"),
        explanation=explanation,
    )


class FakeImages:
    def __init__(self, images):
        self.images = images
        self.removed = []
        self.remove_error = None
        self.prune_filters = None
        self.prune_result = {}

    def list(self):
        return list(self.images)

    def get(self, ref):
        for img in self.images:
            if ref in img.tags or ref == img.id:
                return img
        raise DockerImageNotFound(f"No such image: {ref}")

    def remove(self, ref, force=False):
        if self.remove_error:
            raise self.remove_error
        self.removed.append((ref, force))

    def prune(self, filters=None):
        self.prune_filters = filters
        return self.prune_result


class FakeContainers:
    def __init__(self, containers):
        self.containers = containers

    def list(self, all=False):
        return [c for c in self.containers if all or c.status == "running"]


@pytest.fixture
def fake(monkeypatch):
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


def test_list_images_maps_fields_and_usage(fake):
    images = {(i.tags[0] if i.tags else i.id): i for i in docker_service.list_images()}

    nginx = images["nginx:latest"]
    assert nginx.id == NGINX_ID
    assert nginx.tags == ["nginx:latest", "nginx:1.27"]
    assert nginx.size == 1024
    assert nginx.created_at is not None and nginx.created_at.year == 2026
    assert [(u.name, u.running) for u in nginx.used_by] == [("web", True)]

    # Stopped containers still count as users.
    assert [(u.name, u.running) for u in images["alpine:3.18"].used_by] == [("job", False)]
    assert images["sha256:dangling"].used_by == []


def test_list_images_sorts_by_tag_with_untagged_last(fake):
    order = [i.tags[0] if i.tags else None for i in docker_service.list_images()]
    assert order == ["alpine:3.18", "nginx:latest", None]


def test_list_images_handles_missing_created(fake):
    fake.images.images = [SimpleNamespace(id="sha256:x", tags=["x:1"], attrs={})]
    [img] = docker_service.list_images()
    assert img.created_at is None
    assert img.size == 0


def test_list_images_docker_down(monkeypatch):
    def boom():
        raise DockerException("socket gone")

    client = SimpleNamespace(images=SimpleNamespace(list=boom), containers=FakeContainers([]))
    monkeypatch.setattr(docker_service, "_client", lambda: client)
    with pytest.raises(docker_service.DockerUnavailable):
        docker_service.list_images()


# --- remove_image -------------------------------------------------------------


def test_remove_unused_image(fake):
    fake.containers.containers = []
    docker_service.remove_image("alpine:3.18")
    assert fake.images.removed == [("alpine:3.18", False)]


def test_remove_passes_force(fake):
    docker_service.remove_image("alpine:3.18", force=True)
    assert fake.images.removed == [("alpine:3.18", True)]


def test_remove_missing_image(fake):
    with pytest.raises(docker_service.ImageNotFound):
        docker_service.remove_image("ghost:1")
    assert fake.images.removed == []


@pytest.mark.parametrize("force", [False, True])
def test_remove_refuses_running_image_even_with_force(fake, force):
    with pytest.raises(docker_service.ImageInUse, match="web"):
        docker_service.remove_image("nginx:1.27", force=force)
    assert fake.images.removed == []


def test_remove_conflict_from_docker_is_in_use(fake):
    fake.images.remove_error = _api_error(409, "image is being used by stopped container")
    with pytest.raises(docker_service.ImageInUse, match="stopped container"):
        docker_service.remove_image("alpine:3.18")


def test_remove_other_api_error_is_unavailable(fake):
    fake.images.remove_error = _api_error(500, "daemon exploded")
    with pytest.raises(docker_service.DockerUnavailable):
        docker_service.remove_image("alpine:3.18")


def test_remove_race_where_image_vanishes(fake):
    fake.images.remove_error = DockerImageNotFound("gone")
    with pytest.raises(docker_service.ImageNotFound):
        docker_service.remove_image("alpine:3.18")


# --- prune_images -------------------------------------------------------------


@pytest.mark.parametrize(("all_unused", "dangling"), [(False, True), (True, False)])
def test_prune_filter(fake, all_unused, dangling):
    docker_service.prune_images(all_unused=all_unused)
    assert fake.images.prune_filters == {"dangling": dangling}


def test_prune_counts_deleted_layers_not_untags(fake):
    fake.images.prune_result = {
        "ImagesDeleted": [
            {"Untagged": "alpine:3.18"},
            {"Deleted": "sha256:aaa"},
            {"Deleted": "sha256:bbb"},
        ],
        "SpaceReclaimed": 4096,
    }
    result = docker_service.prune_images(all_unused=True)
    assert result.deleted == ["sha256:aaa", "sha256:bbb"]
    assert result.space_reclaimed == 4096


def test_prune_nothing_to_do(fake):
    # Docker sends null rather than [] when nothing was removed.
    fake.images.prune_result = {"ImagesDeleted": None, "SpaceReclaimed": 0}
    result = docker_service.prune_images()
    assert result.deleted == []
    assert result.space_reclaimed == 0


def test_prune_docker_down(monkeypatch):
    def boom(filters=None):
        raise DockerException("socket gone")

    client = SimpleNamespace(images=SimpleNamespace(prune=boom))
    monkeypatch.setattr(docker_service, "_client", lambda: client)
    with pytest.raises(docker_service.DockerUnavailable):
        docker_service.prune_images()
