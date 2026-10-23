"""DryDock's fail2ban jails: rendering, testing a rule, and the admin routes."""

import base64
import io
import tarfile
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import get_current_user
from app.main import app
from app.schemas.fail2ban import Fail2banConfig, Fail2banJailConfig
from app.services import docker_service, fail2ban_config_service, job_service, settings_service

# Real `fail2ban-regex --print-all-matched` output, from the NAS.
REGEX_OUTPUT = """\
Running tests
=============

Results
=======

Failregex: 2 total
|-  #) [# of hits] regular expression
|   1) [2] ^<HOST> \\S+ \\S+ \\[\\] "[A-Z]+ [^"]*" 401
`-

Lines: 3 lines, 0 ignored, 2 matched, 1 missed
[processed in 0.01 sec]

|- Matched line(s):
|  203.0.113.5 - - [23/Oct/2026:06:00:00 +0000] "GET /wp-login.php HTTP/1.1" 401 1 "-" "M"
|  203.0.113.5 - admin [23/Oct/2026:06:00:01 +0000] "GET / HTTP/2.0" 401 17 "-" "c" 2 "x" "y" 3ms
`-
|- Missed line(s):
|  192.168.10.111 - - [23/Oct/2026:06:00:04 +0000] "GET / HTTP/2.0" 200 120 "-" "M" 5 "x" "y" 5ms
`-
"""


def _config(**overrides: Any) -> Fail2banConfig:
    return Fail2banConfig.model_validate({**fail2ban_config_service.DEFAULT_CONFIG, **overrides})


def test_jails_ban_on_the_forward_hook_and_skip_the_allowlist() -> None:
    jails = fail2ban_config_service.render_jails(_config())

    assert "[drydock-auth]" in jails
    assert "filter        = drydock-auth" in jails
    assert "logpath       = /data/proxy/logs/access.log" in jails
    assert "banaction     = nftables[type=allports, chain_hook=forward]" in jails
    assert "chain         = f2b-docker" in jails
    assert "ignorecommand = grep -qsxF <ip> /data/proxy/allowlist.txt" in jails
    input_hook = fail2ban_config_service.render_jails(_config(ban_hook="input", allowlist_file=""))
    assert "chain_hook" not in input_hook
    assert "ignorecommand" not in input_hook


def test_filters_follow_the_log_format() -> None:
    botsearch = Fail2banJailConfig(name="scan", rule="botsearch")

    text = fail2ban_config_service.render_filter(botsearch, "text")
    json = fail2ban_config_service.render_filter(botsearch, "json")

    assert "before = botsearch-common.conf" in text
    assert '"(?:GET|POST|HEAD) /<block> ' in text
    assert "datepattern" not in text
    assert '"uri":"/<block>' in json
    assert 'datepattern = "ts":{EPOCH}' in json
    # A test filter sits outside filter.d, so its include needs the full path.
    absolute = fail2ban_config_service.render_filter(
        botsearch, "text", include_dir="/etc/fail2ban/filter.d/"
    )
    assert "before = /etc/fail2ban/filter.d/botsearch-common.conf" in absolute


def test_custom_rule_keeps_the_users_regex() -> None:
    jail = Fail2banJailConfig(name="mine", rule="custom", failregex=r"^<HOST> .* 418 ")

    assert "failregex = ^<HOST> .* 418 " in fail2ban_config_service.render_filter(jail, "text")


def test_config_is_validated() -> None:
    with pytest.raises(ValueError, match="unique"):
        _config(jails=[{"name": "a", "rule": "auth"}, {"name": "a", "rule": "forbidden"}])
    with pytest.raises(ValueError, match="<HOST>"):
        _config(jails=[{"name": "a", "rule": "custom", "failregex": "401"}])
    with pytest.raises(ValueError, match="not an IP"):
        _config(ignore_ips=["lan"])
    with pytest.raises(ValueError):
        _config(log_path="/data/$(reboot)")


def test_render_owns_one_jail_file_and_one_filter_per_jail() -> None:
    files = fail2ban_config_service.render(_config())

    assert sorted(files) == [
        "filter.d/drydock-auth.conf",
        "filter.d/drydock-badbots.conf",
        "filter.d/drydock-botsearch.conf",
        "filter.d/drydock-forbidden.conf",
        "jail.d/drydock.local",
    ]


def test_parse_regex_output_counts_ips() -> None:
    result = fail2ban_config_service.parse_test(REGEX_OUTPUT, "text")

    assert (result.lines, result.matched) == (3, 2)
    assert [(hit.ip, hit.count) for hit in result.top_ips] == [("203.0.113.5", 2)]
    assert len(result.samples) == 2


def test_parse_regex_output_reads_json_ips() -> None:
    output = (
        "Lines: 1 lines, 0 ignored, 1 matched, 0 missed\n|- Matched line(s):\n"
        '|  {"ts":1,"request":{"client_ip":"198.51.100.4"},"status":401}\n`-\n'
    )

    result = fail2ban_config_service.parse_test(output, "json")

    assert [hit.ip for hit in result.top_ips] == ["198.51.100.4"]


def test_unexpected_output_is_an_error() -> None:
    with pytest.raises(fail2ban_config_service.Fail2banConfigError):
        fail2ban_config_service.parse_test("Traceback ...", "text")


# --- API ------------------------------------------------------------------------------


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    values: dict[str, Any] = dict(settings_service.DEFAULTS)
    monkeypatch.setattr(settings_service, "get_all", lambda db: values)
    monkeypatch.setattr(settings_service, "set_many", lambda db, patch: values.update(patch))
    return values


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Calls to run_on_host; the jail file reads as missing."""
    calls: list[dict[str, Any]] = []

    def run_on_host(script: str, **kwargs: Any) -> str:
        calls.append({"script": script, **kwargs})
        return REGEX_OUTPUT

    def read_host_file(path: str, **kwargs: Any) -> bytes:
        raise docker_service.DockerNotFound(path)

    monkeypatch.setattr(docker_service, "run_on_host", run_on_host)
    monkeypatch.setattr(docker_service, "read_host_file", read_host_file)
    monkeypatch.setattr("app.services.volume_files_service.helper_image", lambda: "drydock")
    return calls


@pytest.fixture
def client(stored: dict[str, Any], host: list[dict[str, Any]]) -> Iterator[TestClient]:
    app.dependency_overrides[get_current_user] = lambda: type("U", (), {"is_admin": True})()
    app.dependency_overrides[get_db] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_api_starts_from_the_defaults_and_saves(
    client: TestClient, stored: dict[str, Any]
) -> None:
    read = client.get("/api/host/fail2ban/config").json()
    assert [jail["name"] for jail in read["config"]["jails"]] == [
        "auth",
        "botsearch",
        "badbots",
        "forbidden",
    ]
    assert read["applied"] is False

    config = read["config"]
    config["jails"][0]["maxretry"] = 7
    saved = client.put("/api/host/fail2ban/config", json=config)

    assert saved.status_code == 200
    assert stored["fail2ban_config"]["jails"][0]["maxretry"] == 7


def test_api_apply_writes_only_drydock_files_through_a_job(
    client: TestClient, host: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    submitted: list[Any] = []
    monkeypatch.setattr(
        job_service, "submit", lambda kind, label, runner: submitted.append(runner) or _job()
    )

    response = client.post("/api/host/fail2ban/apply")
    assert response.status_code == 202
    ctx = _Context()
    submitted[0](ctx)

    [call] = host
    assert call["writable"] == ("/etc/fail2ban",)
    archive = base64.b64decode(call["environment"]["DRYDOCK_FILES"])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        names = tar.getnames()
    assert all(name.startswith(("jail.d/drydock", "filter.d/drydock-")) for name in names)
    assert "fail2ban-client -t" in call["script"]
    assert ctx.output == REGEX_OUTPUT


def test_api_test_runs_the_rule_over_the_log(client: TestClient, host: list) -> None:
    config = client.get("/api/host/fail2ban/config").json()["config"]

    result = client.post(
        "/api/host/fail2ban/test", json={"config": config, "jail": config["jails"][0]}
    ).json()

    assert result["matched"] == 2
    assert host[0]["writable"] == ("/tmp",)
    assert host[0]["environment"]["LOG_PATH"] == "/data/proxy/logs/access.log"


def test_api_is_admin_only(stored: dict[str, Any]) -> None:
    app.dependency_overrides[get_current_user] = lambda: type("U", (), {"is_admin": False})()
    app.dependency_overrides[get_db] = lambda: None
    try:
        response = TestClient(app).get("/api/host/fail2ban/config")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


class _Context:
    output = ""

    def set_total(self, total: int, message: str | None = None) -> None:
        pass

    def advance(self, message: str | None = None) -> None:
        pass

    def set_output(self, output: str) -> None:
        self.output = output


def _job() -> dict[str, Any]:
    return {
        "id": "j1",
        "kind": "fail2ban_apply",
        "label": "Apply fail2ban jails",
        "status": "pending",
        "total": 0,
        "done": 0,
        "message": None,
        "error": None,
        "output": None,
        "trigger": "manual",
        "created_at": "2026-10-23T00:00:00Z",
        "started_at": None,
        "finished_at": None,
    }
