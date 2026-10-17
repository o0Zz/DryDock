"""docker_service volume usage, against a fake Docker client."""

from types import SimpleNamespace

from app.services import docker_service


def _container(cid, name, status, mounts):
    return SimpleNamespace(id=cid, name=name, status=status, attrs={"Mounts": mounts})


def test_volume_users_include_id_state_and_mount(monkeypatch):
    containers = [
        _container(
            "c1",
            "web",
            "running",
            [
                {"Type": "volume", "Name": "data", "Destination": "/data", "RW": True},
                {"Type": "bind", "Source": "/srv", "Destination": "/srv"},
            ],
        ),
        _container(
            "c2",
            "backup",
            "exited",
            [{"Type": "volume", "Name": "data", "Destination": "/backup", "RW": False}],
        ),
    ]
    client = SimpleNamespace(containers=SimpleNamespace(list=lambda all=False: containers))
    monkeypatch.setattr(docker_service, "_client", lambda: client)

    usage = docker_service._volume_usage()

    assert list(usage) == ["data"]
    assert [(u.id, u.name, u.running, u.destination, u.rw) for u in usage["data"]] == [
        ("c1", "web", True, "/data", True),
        ("c2", "backup", False, "/backup", False),
    ]
