"""Exposing services through the reverse proxy: reading and writing expose.* labels."""

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.main import app
from app.services import (
    compose_service,
    docker_service,
    proxy_service,
    repo_service,
    settings_service,
)

STACK = """\
# Media server
services:
  jellyfin:
    image: jellyfin/jellyfin:latest  # keep this comment
    ports:
      - "8096:8096"
    labels:
      - com.example.owner=me
  db:
    image: postgres:16
    expose:
      - "5432"
"""


def _expose(content: str = STACK, **overrides: object) -> str:
    options: dict = {
        "service": "jellyfin",
        "host": "jellyfin.example.org",
        "port": 8096,
        "public": False,
        "network": "proxy",
    }
    options.update(overrides)
    return proxy_service.expose(content, **options)


def test_expose_writes_neutral_labels_and_network() -> None:
    content = _expose()

    data = yaml.safe_load(content)
    jellyfin = data["services"]["jellyfin"]
    assert jellyfin["labels"] == [
        "com.example.owner=me",
        "expose.host=jellyfin.example.org",
        "expose.port=8096",
        "expose.private=true",
    ]
    # Still on default, so it keeps talking to db.
    assert jellyfin["networks"] == ["default", "proxy"]
    assert data["networks"] == {"proxy": {"external": True}}
    assert "networks" not in data["services"]["db"]
    # Comments and the file's sequence style survive.
    assert "# Media server" in content
    assert "# keep this comment" in content
    assert '      - "8096:8096"' in content


def test_blank_lines_between_blocks_stay_in_place() -> None:
    content = """\
services:
  app:
    image: app
    volumes:
      - data:/data

  other:
    image: other

volumes:
  data:
# end of file
"""
    exposed = _expose(content, service="app", port=80)

    assert "      - proxy\n\n  other:" in exposed
    assert "    image: other\n\nvolumes:" in exposed
    assert exposed.endswith("    external: true\n# end of file\n")
    restored = proxy_service.unexpose(exposed, service="app", network="proxy")
    assert restored == content


def test_crlf_files_keep_their_line_endings() -> None:
    content = STACK.replace("\n", "\r\n")

    exposed = _expose(content)

    assert exposed.count("\r\n") == exposed.count("\n")
    assert proxy_service.unexpose(exposed, service="jellyfin", network="proxy") == content


def test_described_exposure_round_trips() -> None:
    [jellyfin, db] = proxy_service.services(_expose(public=True))

    assert jellyfin.exposed
    assert jellyfin.hosts == ["jellyfin.example.org"]
    assert jellyfin.port == 8096
    assert jellyfin.public
    assert jellyfin.ports == [8096]
    assert not db.exposed
    assert db.ports == [5432]


def test_expose_again_updates_in_place() -> None:
    content = _expose(_expose(), host="tv.example.org", port=8920, public=True)

    labels = yaml.safe_load(content)["services"]["jellyfin"]["labels"]
    assert labels == [
        "com.example.owner=me",
        "expose.host=tv.example.org",
        "expose.port=8920",
        "expose.private=false",
    ]


def test_mapping_labels_and_networks_keep_their_form() -> None:
    content = """\
services:
  app:
    image: app
    labels:
      com.example.owner: me
    networks:
      backend: {}
networks:
  backend: {}
"""
    data = yaml.safe_load(_expose(content, service="app", port=80))

    app_spec = data["services"]["app"]
    assert app_spec["labels"]["expose.host"] == "jellyfin.example.org"
    assert app_spec["labels"]["com.example.owner"] == "me"
    assert set(app_spec["networks"]) == {"backend", "proxy"}
    assert data["networks"] == {"backend": {}, "proxy": {"external": True}}


def test_old_proxy_labels_are_replaced() -> None:
    content = """\
services:
  app:
    image: app
    labels:
      - traefik.enable=true
      - traefik.http.routers.app.rule=Host(`old.example.org`)
      - swag=enable
      - swag_url=old.example.org
      - expose.hsts=true
      - com.example.owner=me
"""
    [before] = proxy_service.services(content)
    assert before.legacy

    labels = yaml.safe_load(_expose(content, service="app", port=80))["services"]["app"]["labels"]

    assert labels == [
        "com.example.owner=me",
        "expose.host=jellyfin.example.org",
        "expose.port=80",
        "expose.private=true",
    ]


def test_unexpose_restores_the_file() -> None:
    content = proxy_service.unexpose(_expose(), service="jellyfin", network="proxy")

    assert yaml.safe_load(content) == yaml.safe_load(STACK)


def test_unexpose_keeps_a_network_other_services_use() -> None:
    both = _expose(_expose(), service="db", host="db.example.org", port=5432)

    data = yaml.safe_load(proxy_service.unexpose(both, service="db", network="proxy"))

    assert data["networks"] == {"proxy": {"external": True}}
    assert "networks" not in data["services"]["db"]


def test_private_unless_said_otherwise() -> None:
    content = """\
services:
  app:
    labels:
      expose.host: a.example.org, b.example.org
"""
    [app_exposure] = proxy_service.services(content)

    assert not app_exposure.public
    assert app_exposure.hosts == ["a.example.org", "b.example.org"]


def test_host_network_service_gets_labels_but_no_network() -> None:
    content = "services:\n  app:\n    network_mode: host\n"

    [app_exposure] = proxy_service.services(content)
    assert app_exposure.blocked is None
    data = yaml.safe_load(_expose(content, service="app", port=81))

    # The sync reaches it through host.docker.internal; it joins no network.
    assert "networks" not in data
    assert "networks" not in data["services"]["app"]
    assert "expose.port=81" in data["services"]["app"]["labels"]


def test_other_network_modes_are_refused() -> None:
    content = "services:\n  app:\n    network_mode: 'service:vpn'\n"

    assert proxy_service.services(content)[0].blocked
    with pytest.raises(proxy_service.ProxyError):
        _expose(content, service="app", port=80)


@pytest.mark.parametrize(
    ("host", "domain", "expected"),
    [
        ("Jellyfin", "example.org", "jellyfin.example.org"),
        ("tv.other.net", "example.org", "tv.other.net"),
        ("jellyfin.", "", None),
        ("bad_name", "example.org", None),
    ],
)
def test_full_host(host: str, domain: str, expected: str | None) -> None:
    if expected is None:
        with pytest.raises(proxy_service.ProxyError):
            proxy_service.full_host(host, domain)
    else:
        assert proxy_service.full_host(host, domain) == expected


def test_long_values_are_not_folded() -> None:
    host = "a-very-long-sub-domain-name-for-this-service." + "x" * 60 + ".example.org"
    content = _expose(host=host)

    assert f"expose.host={host}" in content
    compose_service.validate_yaml(content)


# --- API ------------------------------------------------------------------------------


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    (root / "media").mkdir(parents=True)
    (root / "media" / "docker-compose.yml").write_text(STACK, encoding="utf-8")
    monkeypatch.setattr(settings, "repo_path", root)
    monkeypatch.setattr(docker_service, "list_containers", lambda **kwargs: [])
    monkeypatch.setattr(docker_service, "network_exists", lambda name: True)
    values = {**settings_service.DEFAULTS, "proxy_domain": "example.org"}
    monkeypatch.setattr(settings_service, "get_all", lambda db: values)
    return root


@pytest.fixture
def client(repo: Path) -> Iterator[TestClient]:
    app.dependency_overrides[get_current_user] = lambda: type("U", (), {"is_admin": False})()
    app.dependency_overrides[get_db] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _project_id(repo: Path, name: str = "media") -> str:
    return repo_service.project_id(repo / name / "docker-compose.yml")


def test_api_expose_then_overview_lists_the_route(repo: Path, client: TestClient) -> None:
    project_id = _project_id(repo)
    response = client.post(
        f"/api/proxy/projects/{project_id}/expose",
        # A bare sub-domain gets the proxy domain.
        json={"content": STACK, "service": "jellyfin", "host": "tv", "port": 8096},
    )
    assert response.status_code == 200, response.text
    # Nothing is written until the editor saves.
    assert (repo / "media" / "docker-compose.yml").read_text(encoding="utf-8") == STACK

    (repo / "media" / "docker-compose.yml").write_text(response.json()["content"], "utf-8")
    overview = client.get("/api/proxy").json()

    assert overview["network_exists"] is True
    assert overview["container"] is None
    assert overview["sync"] is None
    assert overview["drydock_image"]
    assert [(r["service"], r["hosts"], r["public"]) for r in overview["routes"]] == [
        ("jellyfin", ["tv.example.org"], False)
    ]


def test_api_refuses_a_host_another_stack_uses(repo: Path, client: TestClient) -> None:
    (repo / "other").mkdir()
    (repo / "other" / "docker-compose.yml").write_text(
        _expose(host="tv.example.org"), encoding="utf-8"
    )

    response = client.post(
        f"/api/proxy/projects/{_project_id(repo)}/expose",
        json={"content": STACK, "service": "jellyfin", "host": "tv.example.org", "port": 8096},
    )

    assert response.status_code == 409
    assert "other/jellyfin" in response.json()["detail"]


def test_api_unknown_service_is_a_bad_request(repo: Path, client: TestClient) -> None:
    response = client.post(
        f"/api/proxy/projects/{_project_id(repo)}/expose",
        json={"content": STACK, "service": "nope", "host": "tv.example.org", "port": 80},
    )

    assert response.status_code == 400


def test_overview_fills_in_env_variables(repo: Path, client: TestClient) -> None:
    (repo / "proxy").mkdir()
    (repo / "proxy" / "docker-compose.yml").write_text(
        """\
services:
  whoami:
    labels:
      - expose.host=whoami.${PROXY_DOMAIN}
      - expose.port=80
""",
        encoding="utf-8",
    )
    (repo / "proxy" / ".env").write_text("# domain\nPROXY_DOMAIN=example.org\n", "utf-8")

    routes = client.get("/api/proxy").json()["routes"]

    assert [route["hosts"] for route in routes] == [["whoami.example.org"]]
