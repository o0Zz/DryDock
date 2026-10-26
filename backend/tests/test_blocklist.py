"""The IP blocklist: parsing lists, the nftables table, the cache and the admin routes."""

import base64
import gzip
import ipaddress
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.main import app
from app.schemas.blocklist import FIREHOL_LEVEL1, IpBlocklistConfig
from app.services import blocklist_service, docker_service, job_service, settings_service

# The head of FireHOL level1, as served.
LIST = """\
#
# firehol_level1
#
0.0.0.0/8
1.10.16.0/20
1.19.0.0/16
10.0.0.0/8
100.64.0.0/10
172.16.0.0/12
192.168.0.0/16
224.0.0.0/3
5.188.10.0/23
5.188.11.0/24
203.0.113.7
not an ip
0.0.0.0/0
2001:db8::/32 ; v6 entry
"""

# `nft list chain` output, with the counters of the drop rules.
CHAINS = """\
table inet drydock_blocklist {
	chain forward {
		type filter hook forward priority filter - 1; policy accept;
		ip saddr @allow4 accept
		ip6 saddr @allow6 accept
		ip saddr @block4 counter packets 12 bytes 720 drop
		ip6 saddr @block6 counter packets 0 bytes 0 drop
	}
}
table inet drydock_blocklist {
	chain input {
		type filter hook input priority filter - 1; policy accept;
		ip saddr @block4 counter packets 3 bytes 180 drop
	}
}
"""


def _nets(*values: str) -> list[Any]:
    return [ipaddress.ip_network(value) for value in values]


def test_parse_keeps_public_ranges_only() -> None:
    parsed = [str(n) for n in blocklist_service.parse(LIST)]

    assert parsed == [
        "1.10.16.0/20",
        "1.19.0.0/16",
        "5.188.10.0/23",
        "5.188.11.0/24",
        "203.0.113.7/32",
        "2001:db8::/32",
    ]


def test_collapse_merges_overlaps_per_family() -> None:
    merged = blocklist_service.collapse(_nets("5.188.11.0/24", "2001:db8::/32", "5.188.10.0/23"))

    assert [str(n) for n in merged] == ["5.188.10.0/23", "2001:db8::/32"]


def test_render_swaps_the_table_and_lets_the_allowlist_through_first() -> None:
    ruleset = blocklist_service.render(_nets("1.19.0.0/16"), _nets("192.168.0.0/16", "::1/128"))

    assert ruleset.index("table inet drydock_blocklist\n") < ruleset.index(
        "delete table inet drydock_blocklist"
    )
    for hook in ("forward", "input"):
        assert f"type filter hook {hook} priority -1; policy accept;" in ruleset
    assert ruleset.index("ip saddr @allow4 accept") < ruleset.index("ip saddr @block4 counter drop")
    assert "1.19.0.0/16" in ruleset
    # An empty set must not get an empty `elements = {}`: nft refuses it.
    block6 = ruleset.split("set block6 {")[1].split("}")[0]
    assert "elements" not in block6


@pytest.fixture
def data(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(settings, "data_path", tmp_path)
    return tmp_path


@pytest.fixture
def stored(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    values: dict[str, Any] = dict(settings_service.DEFAULTS)
    monkeypatch.setattr(settings_service, "get_all", lambda db: values)
    monkeypatch.setattr(settings_service, "set_many", lambda db, patch: values.update(patch))
    return values


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Calls to run_on_host; the allowlist file holds the public IP and a trusted one."""
    calls: list[dict[str, Any]] = []

    def run_on_host(script: str, **kwargs: Any) -> str:
        calls.append({"script": script, **kwargs})
        return CHAINS if "nft list chain inet drydock_blocklist input" in script else "loaded"

    def read_host_file(path: str, **kwargs: Any) -> bytes:
        assert path == "/data/proxy/allowlist.txt"
        return b"192.168.10.0/24\n86.193.174.93\n1.19.0.5\n"

    monkeypatch.setattr(docker_service, "run_on_host", run_on_host)
    monkeypatch.setattr(docker_service, "read_host_file", read_host_file)
    monkeypatch.setattr("app.services.volume_files_service.helper_image", lambda: "drydock")
    return calls


@pytest.fixture
def lists(monkeypatch: pytest.MonkeyPatch) -> dict[str, str | Exception]:
    """What each URL answers: a list, or an error."""
    answers: dict[str, str | Exception] = {FIREHOL_LEVEL1: LIST}

    def fetch(url: str) -> list[Any]:
        answer = answers[url]
        if isinstance(answer, Exception):
            raise answer
        return blocklist_service.parse(answer)

    monkeypatch.setattr(blocklist_service, "fetch", fetch)
    return answers


def test_apply_loads_the_table_on_the_host_network(
    data: Path, host: list[dict[str, Any]], lists: dict[str, Any]
) -> None:
    output = blocklist_service.apply(IpBlocklistConfig(enabled=True))

    assert output == "loaded"
    [call] = host
    assert call["host_network"] is True
    assert "nft -f -" in call["script"]
    ruleset = gzip.decompress(base64.b64decode(call["environment"]["DRYDOCK_RULESET"])).decode()
    assert "5.188.10.0/23" in ruleset
    assert "5.188.11.0/24" not in ruleset  # merged into the /23
    assert "192.168.0.0/16" in ruleset.split("set allow4")[1].split("}")[0]

    status = blocklist_service.status()
    assert status is not None
    assert status.entries == 5
    assert status.sources[0].error is None


def test_check_reads_the_last_loaded_list(
    data: Path, host: list[dict[str, Any]], lists: dict[str, Any]
) -> None:
    blocklist_service.apply(IpBlocklistConfig(enabled=True))

    blocked = blocklist_service.check("5.188.10.9")
    assert blocked.blocked is True
    assert blocked.network == "5.188.10.0/23"
    # On the list, but in the allowlist file.
    trusted = blocklist_service.check("1.19.0.5")
    assert trusted.blocked is False
    assert trusted.allowed_by == "1.19.0.5/32"
    assert blocklist_service.check("8.8.8.8").blocked is False
    with pytest.raises(ValueError):
        blocklist_service.check("nope")


def test_a_failing_source_keeps_its_previous_ranges(
    data: Path, host: list[dict[str, Any]], lists: dict[str, Any]
) -> None:
    blocklist_service.apply(IpBlocklistConfig(enabled=True))
    lists[FIREHOL_LEVEL1] = blocklist_service.BlocklistError("timed out")

    blocklist_service.apply(IpBlocklistConfig(enabled=True))

    status = blocklist_service.status()
    assert status is not None
    assert status.entries == 5
    assert status.sources[0].error == "timed out"


def test_nothing_to_load_is_an_error(
    data: Path, host: list[dict[str, Any]], lists: dict[str, Any]
) -> None:
    lists[FIREHOL_LEVEL1] = blocklist_service.BlocklistError("timed out")

    with pytest.raises(blocklist_service.BlocklistError, match="No list could be downloaded"):
        blocklist_service.apply(IpBlocklistConfig(enabled=True))
    assert host == []


def test_disabled_removes_the_table(data: Path, host: list[dict[str, Any]]) -> None:
    blocklist_service.apply(IpBlocklistConfig(enabled=False))

    [call] = host
    assert "nft delete table inet drydock_blocklist" in call["script"]


def test_host_state_sums_the_drop_counters(host: list[dict[str, Any]]) -> None:
    state = blocklist_service.host_state()

    assert state.active is True
    assert state.dropped == 15


def test_config_is_validated() -> None:
    with pytest.raises(ValueError):
        IpBlocklistConfig(sources=["ftp://example.org/list"])
    with pytest.raises(ValueError):
        IpBlocklistConfig(ignore_ips=["nope"])
    with pytest.raises(ValueError):
        IpBlocklistConfig(allowlist_file="relative/path")


@pytest.fixture
def client(
    data: Path, stored: dict[str, Any], host: list[dict[str, Any]]
) -> Iterator[TestClient]:
    app.dependency_overrides[get_current_user] = lambda: type("U", (), {"is_admin": True})()
    app.dependency_overrides[get_db] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_api_saves_and_applies_through_a_job(
    client: TestClient,
    stored: dict[str, Any],
    lists: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read = client.get("/api/host/blocklist").json()
    assert read["config"]["enabled"] is False
    assert read["config"]["sources"] == [FIREHOL_LEVEL1]
    assert read["status"] is None
    assert read["host"] == {"active": True, "dropped": 15, "error": None}

    saved = client.put("/api/host/blocklist", json={**read["config"], "enabled": True})
    assert saved.status_code == 200
    assert stored["ip_blocklist"]["enabled"] is True

    submitted: list[Any] = []
    monkeypatch.setattr(
        job_service, "submit", lambda kind, label, runner: submitted.append(runner) or _job()
    )
    assert client.post("/api/host/blocklist/apply").status_code == 202
    ctx = _Context()
    submitted[0](ctx)
    assert ctx.message == "Blocklist loaded: 5 ranges"

    checked = client.get("/api/host/blocklist/check", params={"ip": "1.10.16.1"}).json()
    assert checked["blocked"] is True
    assert client.get("/api/host/blocklist/check", params={"ip": "x"}).status_code == 400


def test_api_is_admin_only(stored: dict[str, Any]) -> None:
    app.dependency_overrides[get_current_user] = lambda: type("U", (), {"is_admin": False})()
    app.dependency_overrides[get_db] = lambda: None
    try:
        response = TestClient(app).get("/api/host/blocklist")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


class _Context:
    db = None
    message = ""
    output = ""

    def set_total(self, total: int, message: str | None = None) -> None:
        pass

    def advance(self, message: str | None = None) -> None:
        self.message = message or ""

    def set_output(self, output: str) -> None:
        self.output = output


def _job() -> dict[str, Any]:
    return {
        "id": "j1",
        "kind": "blocklist_apply",
        "label": "Apply the IP blocklist",
        "status": "pending",
        "total": 0,
        "done": 0,
        "message": None,
        "error": None,
        "output": None,
        "trigger": "manual",
        "created_at": "2026-10-24T00:00:00Z",
        "started_at": None,
        "finished_at": None,
    }
