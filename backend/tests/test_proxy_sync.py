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

    config = yaml.safe_load(proxy_sync.render_traefik(routes, sources, Config()))["http"]

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


ROUTES = [
    Route("mstream", ("music.example.org",), "http://mstream:3000", False),
    Route("drydock", ("drydock.example.org",), "http://drydock:8080", True),
    Route("home-assistant", ("home.example.org",), "http://host.docker.internal:81", False),
    Route("api", ("api.dev.example.org",), "http://api:5000", False),
]
SOURCES = ["192.168.10.0/24", "198.51.100.4"]


def test_nginx_config_for_swag() -> None:
    conf = proxy_sync.render_nginx(ROUTES, SOURCES, Config(proxy="swag"))
    blocks = {
        block.split("server_name ")[1].split(";")[0]: block for block in conf.split("\n\n")[1:]
    }

    music = blocks["music.example.org"]
    assert "include /config/nginx/ssl.conf;" in music
    assert 'add_header Strict-Transport-Security "max-age=15768000" always;' in music
    assert "set $upstream_app mstream;" in music
    assert "deny all;" not in music
    # Private: the allowlist, then everyone else refused.
    drydock = blocks["drydock.example.org"]
    assert "allow 192.168.10.0/24;\n    allow 198.51.100.4;\n    deny all;" in drydock
    # A fixed name, so nginx reads it from /etc/hosts.
    assert "proxy_pass http://host.docker.internal:81;" in blocks["home.example.org"]


def test_caddyfile_groups_hosts_under_wildcard_sites() -> None:
    caddyfile = proxy_sync.render_caddy(
        ROUTES, SOURCES, Config(proxy="caddy", dns_provider="ovh")
    )

    assert "\tacme_dns ovh {" in caddyfile
    assert "\n*.example.org {\n\timport common\n" in caddyfile
    assert "\n*.dev.example.org {\n" in caddyfile
    assert "music.example.org {" not in caddyfile
    assert "\t@drydock_example_org host drydock.example.org\n" in caddyfile
    assert "\thandle @drydock_example_org {\n" in caddyfile
    assert "\t\t@blocked not remote_ip 192.168.10.0/24 198.51.100.4\n" in caddyfile
    assert "\t\treverse_proxy host.docker.internal:81\n" in caddyfile
    assert "\t\tformat json\n" in caddyfile
    # Only the private route is filtered.
    assert caddyfile.count("@blocked not remote_ip") == 1


class _Exec:
    def __init__(self, results: dict[str, Any]) -> None:
        self.results = results
        self.calls: list[list[str]] = []

    def get(self, name: str) -> "_Exec":
        if self.results.get("missing"):
            raise proxy_sync.DockerException("No such container")
        return self

    def exec_run(self, command: list[str]) -> Any:
        self.calls.append(command)
        code = self.results.get(command[0], 0)
        return type("R", (), {"exit_code": code, "output": b"emerg: bad"})()


def _client(**results: Any) -> Any:
    return type("C", (), {"containers": _Exec(results)})()


def test_deploy_checks_then_reloads(tmp_path: Path) -> None:
    config = Config(proxy="swag", output=tmp_path, proxy_container="swag")
    client = _client()

    result = proxy_sync.deploy(client, config, proxy_sync.WRITERS["swag"], "server {}\n")
    assert result == "changed"
    assert client.containers.calls == [["nginx", "-t"], ["nginx", "-s", "reload"]]
    # Same content: nothing to do.
    result = proxy_sync.deploy(client, config, proxy_sync.WRITERS["swag"], "server {}\n")
    assert result == "unchanged"


def test_rejected_config_puts_the_previous_one_back(tmp_path: Path) -> None:
    config = Config(proxy="swag", output=tmp_path, proxy_container="swag")
    (tmp_path / "drydock-expose.conf").write_text("good\n", encoding="utf-8")

    result = proxy_sync.deploy(_client(nginx=1), config, proxy_sync.WRITERS["swag"], "bad\n")

    assert result == "rejected"
    assert (tmp_path / "drydock-expose.conf").read_text(encoding="utf-8") == "good\n"


def test_proxy_not_running_keeps_the_new_file(tmp_path: Path) -> None:
    config = Config(proxy="caddy", output=tmp_path, proxy_container="caddy")

    result = proxy_sync.deploy(_client(missing=True), config, proxy_sync.WRITERS["caddy"], "x\n")
    assert result == "changed"
    assert (tmp_path / "Caddyfile").read_text(encoding="utf-8") == "x\n"


def test_nginx_leaves_hsts_to_swags_ssl_conf(tmp_path: Path) -> None:
    (tmp_path / "ssl.conf").write_text(
        '#add_header X-Frame-Options "SAMEORIGIN";\n'
        'add_header Strict-Transport-Security "max-age=63072000";\n',
        encoding="utf-8",
    )
    assert proxy_sync.ssl_conf_sets_hsts(tmp_path / "ssl.conf")
    assert not proxy_sync.ssl_conf_sets_hsts(tmp_path / "missing.conf")

    conf = proxy_sync.render_nginx(ROUTES, SOURCES, Config(proxy="swag", ssl_conf_hsts=True))

    assert "Strict-Transport-Security" not in conf


def test_caddy_without_dns_api_gets_one_certificate_per_name() -> None:
    caddyfile = proxy_sync.render_caddy(ROUTES, SOURCES, Config(proxy="caddy"))

    assert "acme_dns" not in caddyfile
    assert "*." not in caddyfile
    assert "\nmusic.example.org {\n" in caddyfile
    assert "\napi.dev.example.org {\n" in caddyfile


def test_caddy_with_cloudflare() -> None:
    config = Config(proxy="caddy", dns_provider="cloudflare")

    caddyfile = proxy_sync.render_caddy(ROUTES, SOURCES, config)

    assert "\tacme_dns cloudflare {$CF_DNS_API_TOKEN}\n" in caddyfile
    assert "\n*.example.org {\n" in caddyfile
