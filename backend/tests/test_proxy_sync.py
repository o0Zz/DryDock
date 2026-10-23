"""The proxy sync: expose.* labels of running containers to the proxy's config."""

from pathlib import Path
from typing import Any

import yaml

from app import proxy_sync
from app.proxy_sync import Config, Route


def _container(
    name: str,
    *,
    host: str = "app.example.org",
    port: str = "80",
    networks: tuple[str, ...] = ("proxy",),
    mode: str = "proxy",
    **labels: str,
) -> dict[str, Any]:
    """A container as `GET /containers/json` lists it."""
    return {
        "Names": [f"/{name}"],
        "Labels": {
            "expose.host": host,
            "expose.port": port,
            **{f"expose.{key}": value for key, value in labels.items()},
        },
        "HostConfig": {"NetworkMode": mode},
        "NetworkSettings": {"Networks": {network: {} for network in networks}},
    }


def test_routes_reach_containers_by_name_on_the_network() -> None:
    routes, problems = proxy_sync.routes_from(
        [
            _container("mstream", host="music.example.org", port="3000", private="false"),
            _container("drydock", host="DryDock.example.org", port="8080"),
        ],
        "proxy",
    )

    assert problems == []
    # Private unless a label says otherwise.
    assert routes == [
        Route("drydock", ("drydock.example.org",), "http://drydock:8080", True),
        Route("mstream", ("music.example.org",), "http://mstream:3000", False),
    ]


def test_host_network_goes_through_the_host_gateway() -> None:
    [route], _ = proxy_sync.routes_from(
        [_container("home-assistant", port="81", networks=(), mode="host")], "proxy"
    )

    assert route.url == "http://host.docker.internal:81"


def test_unreachable_or_broken_containers_are_skipped() -> None:
    routes, problems = proxy_sync.routes_from(
        [
            _container("lonely", networks=("default",)),
            _container("noport", port=""),
            _container("badhost", host="not a host"),
            _container("first", host="dup.example.org"),
            _container("second", host="dup.example.org"),
        ],
        "proxy",
    )

    assert [route.name for route in routes] == ["first"]
    assert len(problems) == 4
    assert any("second: dup.example.org already used by first" in p for p in problems)


def test_traefik_config() -> None:
    routes = [
        Route("mstream", ("music.example.org",), "http://mstream:3000", False),
        Route("gitea", ("git.example.org", "g.example.org"), "http://gitea:3000", True),
    ]
    sources = proxy_sync.allowlist(
        Config(lan_ranges=["192.168.10.0/24"], trusted_ips=["203.0.113.7"]), "198.51.100.4"
    )

    config = yaml.safe_load(proxy_sync.render_traefik(routes, sources, "websecure"))["http"]

    assert config["routers"]["mstream"] == {
        "rule": "Host(`music.example.org`)",
        "entryPoints": ["websecure"],
        "service": "mstream",
        "middlewares": ["hsts"],
    }
    assert config["routers"]["gitea"]["rule"] == "Host(`git.example.org`) || Host(`g.example.org`)"
    assert config["routers"]["gitea"]["middlewares"] == ["private", "hsts"]
    assert config["services"]["gitea"] == {
        "loadBalancer": {"servers": [{"url": "http://gitea:3000"}]}
    }
    assert config["middlewares"]["private"]["ipAllowList"]["sourceRange"] == [
        "192.168.10.0/24",
        "198.51.100.4",
        "203.0.113.7",
    ]


def test_unknown_public_ip_keeps_the_rest_of_the_allowlist() -> None:
    assert proxy_sync.allowlist(Config(lan_ranges=["10.0.0.0/8"]), None) == ["10.0.0.0/8"]


def test_write_only_on_change(tmp_path: Path) -> None:
    target = tmp_path / "expose.yml"

    assert proxy_sync.write_if_changed(target, "a: 1\n")
    assert not proxy_sync.write_if_changed(target, "a: 1\n")
    assert proxy_sync.write_if_changed(target, "a: 2\n")
    assert target.read_text(encoding="utf-8") == "a: 2\n"
    assert [path.name for path in tmp_path.iterdir()] == ["expose.yml"]
