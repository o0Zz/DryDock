"""End-to-end check of the image helpers against a real Docker daemon.

Skipped when no daemon is reachable. Builds tiny throwaway images from
``scratch`` so nothing is pulled and no existing image is touched.
"""

import contextlib
import io
import os
import uuid

import docker
import pytest

from app.services import docker_service


@pytest.fixture(scope="module")
def daemon():
    try:
        client = docker.from_env()
        client.ping()
    except docker.errors.DockerException as exc:
        pytest.skip(f"Docker daemon not available: {exc}")
    docker_service._reset_client()
    return client


def _build(daemon, tag=None):
    dockerfile = io.BytesIO(f'FROM scratch\nLABEL drydock.test="{uuid.uuid4().hex}"\n'.encode())
    image, _ = daemon.images.build(fileobj=dockerfile, tag=tag, rm=True)
    return image.id


def _cleanup(daemon, image_id):
    for c in daemon.containers.list(all=True, filters={"ancestor": image_id}):
        c.remove(force=True)
    with contextlib.suppress(docker.errors.ImageNotFound):
        daemon.images.remove(image_id, force=True)


@pytest.fixture
def scratch_image(daemon):
    tag = f"drydock-test/{uuid.uuid4().hex[:12]}:1"
    image_id = _build(daemon, tag)
    yield tag, image_id
    _cleanup(daemon, image_id)


def _find(tag):
    return next((i for i in docker_service.list_images() if tag in i.tags), None)


def test_list_and_delete_unused_image(scratch_image):
    tag, image_id = scratch_image

    listed = _find(tag)
    assert listed is not None
    assert listed.id == image_id
    assert listed.used_by == []

    docker_service.remove_image(tag)

    assert _find(tag) is None
    with pytest.raises(docker_service.ImageNotFound):
        docker_service.remove_image(tag)


def test_stopped_container_blocks_delete_until_forced(daemon, scratch_image):
    tag, image_id = scratch_image
    container = daemon.containers.create(
        tag, command=["/nothing"], name=f"dd-{uuid.uuid4().hex[:8]}"
    )

    listed = _find(tag)
    assert [(u.name, u.running) for u in listed.used_by] == [(container.name, False)]

    with pytest.raises(docker_service.ImageInUse):
        docker_service.remove_image(tag)
    assert _find(tag) is not None

    # Forced: Docker only untags, the stopped container keeps its image.
    docker_service.remove_image(tag, force=True)
    assert _find(tag) is None
    assert daemon.images.get(image_id) is not None


@pytest.mark.skipif(
    os.environ.get("DRYDOCK_TEST_PRUNE") != "1",
    reason="prunes every dangling image on the host; set DRYDOCK_TEST_PRUNE=1 to run",
)
def test_prune_dangling_removes_untagged_image(daemon):
    image_id = _build(daemon)
    try:
        result = docker_service.prune_images()
        assert image_id in result.deleted
        with pytest.raises(docker.errors.ImageNotFound):
            daemon.images.get(image_id)
    finally:
        _cleanup(daemon, image_id)
