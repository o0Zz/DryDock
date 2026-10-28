"""fail2ban's jails: reading the host's files, editing them in place, the host side, the routes."""

import base64
import gzip
import io
import tarfile
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import get_current_user
from app.main import app
from app.schemas.fail2ban import Fail2banEdit, Fail2banTestRequest
from app.services import docker_service, fail2ban_config_service, job_service
from app.services import fail2ban_ini as ini
from app.services import fail2ban_jails as jails_service
from app.services.fail2ban_jails import Fail2banPlanError, Snapshot

# The layers of a Debian host (the NAS): the package's jail.conf and defaults-debian.conf,
# the owner's jail.local, and DryDock's old single file.
FILES = {
    "jail.conf": """\
[DEFAULT]
# "bantime" is the number of seconds that a host is banned.
bantime  = 10m
findtime  = 10m
maxretry = 5
backend = auto
mode = normal
filter = %(__name__)s[mode=%(mode)s]

[sshd]
port    = ssh
logpath = %(sshd_log)s
backend = %(sshd_backend)s

[apache-badbots]
port     = http,https
logpath  = %(apache_access_log)s
""",
    "jail.d/defaults-debian.conf": """\
[DEFAULT]
banaction = nftables

[sshd]
backend = systemd
journalmatch = _SYSTEMD_UNIT=ssh.service + _COMM=sshd
enabled = true
""",
    "jail.local": """\
[sshd]
enabled = true
port = ssh
filter = sshd
logpath = /var/log/auth.log
maxretry = 5
findtime = 600
bantime = 86400
""",
    "jail.d/drydock.local": """\
# Managed by DryDock (Host page, fail2ban). Edits here are overwritten.

[drydock-auth]
enabled       = true
filter        = drydock-auth
logpath       = /data/proxy/logs/access.log
maxretry      = 3
""",
    "filter.d/sshd.conf": """\
[INCLUDES]
before = common.conf

[Definition]
failregex = ^Failed \\S+ for <HOST>
            ^Invalid \\S+ from <HOST>
ignoreregex =
""",
    "filter.d/drydock-auth.conf": """\
# Managed by DryDock: rule auth, text access log.
[Definition]
failregex = ^<HOST> \\S+ \\S+ \\[\\] "[A-Z]+ [^"]*" 401
ignoreregex =
""",
}
# `fail2ban-client -d` for these files, as fail2ban 1.1 prints it.
DUMP = """\
['set', 'loglevel', 'INFO']
['add', 'drydock-auth', 'auto']
['set', 'drydock-auth', 'addlogpath', '/data/proxy/logs/access.log', 'head']
['set', 'drydock-auth', 'addfailregex', '^<HOST> \\\\S+ \\\\S+ \\\\[\\\\] "[A-Z]+ [^"]*" 401']
['set', 'drydock-auth', 'maxretry', 3]
['set', 'drydock-auth', 'findtime', '10m']
['set', 'drydock-auth', 'bantime', '10m']
['start', 'drydock-auth']
['add', 'sshd', 'systemd']
['multi-set', 'sshd', 'addfailregex', ['^Failed \\\\S+ for <HOST>', '^Invalid \\\\S+ from <HOST>']]
['set', 'sshd', 'maxretry', 5]
['set', 'sshd', 'findtime', '600']
['set', 'sshd', 'bantime', '86400']
['start', 'sshd']
"""
# Real `fail2ban-regex --print-all-matched` output, from the NAS.
REGEX_OUTPUT = """\
Results
=======

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


def _snapshot(**files: str | None) -> Snapshot:
    merged = {**FILES, **files}
    return Snapshot(
        files={path: text for path, text in merged.items() if text is not None}, dump=DUMP
    )


def _plan(snapshot: Snapshot | None = None, **edit: Any) -> dict[str, str | None]:
    return jails_service.plan(snapshot or _snapshot(), Fail2banEdit.model_validate(edit))


def _jail(name: str) -> Any:
    return next(jail for jail in jails_service.read_jails(_snapshot()) if jail.name == name)


# --- INI editing ------------------------------------------------------------------------


def test_ini_edits_one_key_and_keeps_the_rest() -> None:
    text = "# mine\n[sshd]\nmaxretry = 5  \nfailregex = a\n    b\n\n[other]\nmaxretry = 1\n"

    assert ini.get(text, "sshd", "failregex") == ["a", "b"]
    changed = ini.set_value(text, "sshd", "failregex", ["x", "y"])
    assert (
        changed
        == "# mine\n[sshd]\nmaxretry = 5  \nfailregex = x\n            y\n\n[other]\nmaxretry = 1\n"
    )
    added = ini.set_value(text, "sshd", "bantime", ["1d"])
    assert "    b\nbantime = 1d\n\n[other]" in added
    assert ini.set_value(text, "new", "enabled", ["true"]).endswith(
        "maxretry = 1\n\n[new]\nenabled = true\n"
    )
    assert (
        ini.set_value(text, "sshd", "failregex", None)
        == "# mine\n[sshd]\nmaxretry = 5  \n\n[other]\nmaxretry = 1\n"
    )


# --- Reading ----------------------------------------------------------------------------


def test_sshd_is_read_through_every_layer() -> None:
    sshd = _jail("sshd")

    assert sshd.enabled and not sshd.managed
    assert sshd.backend == "systemd"
    # jail.local sets a logpath, but the systemd backend reads the journal.
    assert sshd.logpath == []
    assert sshd.sources["logpath"] == "jail.local:5"
    assert sshd.filter == "sshd"
    assert sshd.failregex == ["^Failed \\S+ for <HOST>", "^Invalid \\S+ from <HOST>"]
    assert (sshd.maxretry, sshd.findtime, sshd.bantime) == ("5", "600", "86400")
    assert sshd.sources["maxretry"] == "jail.local:6"
    assert sshd.sources["failregex"] == "filter.d/sshd.conf:5"
    assert sshd.dump[0] == "['add', 'sshd', 'systemd']"
    # Not started, not touched by a .local file: not listed.
    assert "apache-badbots" not in [jail.name for jail in jails_service.read_jails(_snapshot())]


def test_a_disabled_jail_is_read_from_its_files() -> None:
    snapshot = _snapshot(
        **{"jail.local": FILES["jail.local"].replace("enabled = true", "enabled = false")}
    )
    snapshot.files["jail.d/defaults-debian.conf"] = ""
    snapshot.dump = ""

    sshd = next(jail for jail in jails_service.read_jails(snapshot) if jail.name == "sshd")

    assert not sshd.enabled
    assert sshd.logpath == ["/var/log/auth.log"]
    assert sshd.failregex[0] == "^Failed \\S+ for <HOST>"


# --- Editing in place -------------------------------------------------------------------


def test_a_key_set_in_jail_local_is_edited_there() -> None:
    changes = _plan(changes=[{"name": "sshd", "maxretry": "3", "bantime": "1d"}])

    assert list(changes) == ["jail.local"]
    assert "maxretry = 3\nfindtime = 600\nbantime = 1d\n" in changes["jail.local"]


def test_a_key_from_a_package_file_goes_to_jail_local() -> None:
    # `enabled` is last set by jail.local here; drop it there so it comes from the package.
    local = FILES["jail.local"].replace("enabled = true\n", "")

    changes = _plan(
        _snapshot(**{"jail.local": local}), changes=[{"name": "sshd", "enabled": False}]
    )

    assert list(changes) == ["jail.local"]
    assert ini.get(changes["jail.local"] or "", "sshd", "enabled") == ["false"]


def test_a_regex_of_a_package_filter_goes_to_its_local_twin() -> None:
    changes = _plan(changes=[{"name": "sshd", "failregex": ["^Failed \\S+ for <HOST>"]}])

    assert list(changes) == ["filter.d/sshd.local"]
    assert ini.get(changes["filter.d/sshd.local"] or "", "Definition", "failregex") == [
        "^Failed \\S+ for <HOST>"
    ]


def test_bad_edits_are_refused() -> None:
    with pytest.raises(Fail2banPlanError, match="<HOST>"):
        _plan(changes=[{"name": "sshd", "failregex": ["no host"]}])
    with pytest.raises(Fail2banPlanError, match="no jail"):
        _plan(changes=[{"name": "nope", "maxretry": "3"}])


# --- One file pair per jail -------------------------------------------------------------


def test_a_new_jail_gets_its_own_files() -> None:
    changes = _plan(
        changes=[
            {
                "name": "scanners",
                "create": {"template": "botsearch", "log_format": "json"},
                "failregex": ['"client_ip":"<HOST>".*"status":404'],
                "maxretry": "2",
            }
        ]
    )

    jail, filter_ = changes["jail.d/scanners.local"] or "", changes["filter.d/scanners.conf"] or ""
    assert jail.startswith(jails_service.MARKER)
    assert ini.get(jail, "scanners", "filter") == ["scanners"]
    assert ini.get(jail, "scanners", "banaction") == ["nftables[type=allports, chain_hook=forward]"]
    assert ini.get(jail, "scanners", "maxretry") == ["2"]
    assert "before = botsearch-common.conf" in filter_
    assert 'datepattern = "ts":{EPOCH}' in filter_
    # Once created, it is edited in its own files.
    snapshot = _snapshot(**changes)
    edited = _plan(snapshot, changes=[{"name": "scanners", "bantime": "1h", "ignoreregex": ["x"]}])
    assert sorted(edited) == ["filter.d/scanners.conf", "jail.d/scanners.local"]
    assert next(
        jail for jail in jails_service.read_jails(snapshot) if jail.name == "scanners"
    ).managed


def test_a_new_jail_needs_a_free_name() -> None:
    for name in ("sshd", "apache-badbots", "drydock-auth"):
        with pytest.raises(Fail2banPlanError, match="taken"):
            _plan(changes=[{"name": name, "create": {"template": "auth"}, "failregex": ["<HOST>"]}])


def test_only_drydocks_jails_are_deleted() -> None:
    created = _plan(
        changes=[{"name": "auth", "create": {"template": "auth"}, "failregex": ["<HOST>"]}]
    )

    removed = _plan(_snapshot(**created), changes=[{"name": "auth", "delete": True}])

    assert removed == {"filter.d/auth.conf": None, "jail.d/auth.local": None}
    with pytest.raises(Fail2banPlanError, match="turn it off"):
        _plan(changes=[{"name": "sshd", "delete": True}])


def test_the_old_single_file_is_split() -> None:
    changes = _plan(convert_legacy=True)

    assert changes["jail.d/drydock.local"] is None
    assert changes["filter.d/drydock-auth.conf"] is None
    jail = changes["jail.d/auth.local"] or ""
    assert jail.startswith(jails_service.MARKER)
    assert ini.get(jail, "auth", "filter") == ["auth"]
    assert ini.get(jail, "auth", "maxretry") == ["3"]
    assert changes["filter.d/auth.conf"] == FILES["filter.d/drydock-auth.conf"]


# --- Host side --------------------------------------------------------------------------


def _read_output() -> str:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for path, text in FILES.items():
            data = text.replace("\n", "\r\n").encode()
            info = tarfile.TarInfo(f"./{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    encoded = base64.b64encode(gzip.compress(buffer.getvalue())).decode()
    return f"{DUMP}--DRYDOCK-FILES--\n{encoded}"


def test_snapshot_reads_the_dump_and_the_files(host: list[dict[str, Any]]) -> None:
    host_output["value"] = _read_output()

    snapshot = fail2ban_config_service.snapshot()

    assert snapshot.files == FILES
    assert snapshot.dump.startswith("['set', 'loglevel', 'INFO']")
    assert "writable" not in host[0]


def test_test_includes_the_jails_own_filter(host: list[dict[str, Any]]) -> None:
    host_output["value"] = REGEX_OUTPUT
    request = Fail2banTestRequest(logpath="/var/log/auth.log", failregex=["<HOST>"], filter="sshd")

    result = fail2ban_config_service.test(request)

    rendered = base64.b64decode(host[0]["environment"]["DRYDOCK_FILTER"]).decode()
    assert "before = /etc/fail2ban/filter.d/sshd.conf" in rendered
    assert (result.lines, result.matched) == (3, 2)
    assert [(hit.ip, hit.count) for hit in result.top_ips] == [("203.0.113.5", 2)]


def test_parse_regex_output_reads_json_ips() -> None:
    output = (
        "Lines: 1 lines, 0 ignored, 1 matched, 0 missed\n|- Matched line(s):\n"
        '|  {"ts":1,"request":{"client_ip":"198.51.100.4"},"status":401}\n`-\n'
    )

    assert [hit.ip for hit in fail2ban_config_service.parse_test(output).top_ips] == [
        "198.51.100.4"
    ]


def test_unexpected_output_is_an_error() -> None:
    with pytest.raises(fail2ban_config_service.Fail2banConfigError):
        fail2ban_config_service.parse_test("Traceback ...")


# --- API ------------------------------------------------------------------------------


host_output: dict[str, str] = {"value": ""}


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Calls to run_on_host, answering with `host_output`."""
    calls: list[dict[str, Any]] = []

    def run_on_host(script: str, **kwargs: Any) -> str:
        calls.append({"script": script, **kwargs})
        return host_output["value"]

    monkeypatch.setattr(docker_service, "run_on_host", run_on_host)
    monkeypatch.setattr("app.services.volume_files_service.helper_image", lambda: "drydock")
    return calls


@pytest.fixture
def client(host: list[dict[str, Any]]) -> Iterator[TestClient]:
    host_output["value"] = _read_output()
    app.dependency_overrides[get_current_user] = lambda: type("U", (), {"is_admin": True})()
    app.dependency_overrides[get_db] = lambda: None
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_api_lists_the_hosts_jails(client: TestClient) -> None:
    read = client.get("/api/host/fail2ban/jails").json()

    assert [jail["name"] for jail in read["jails"]] == ["drydock-auth", "sshd"]
    assert read["legacy"] is True
    assert read["templates"]["botsearch"]["before"] == "botsearch-common.conf"


def test_api_plans_without_writing(client: TestClient, host: list[dict[str, Any]]) -> None:
    response = client.post(
        "/api/host/fail2ban/plan", json={"changes": [{"name": "sshd", "maxretry": "3"}]}
    )

    [change] = response.json()["files"]
    assert change["path"] == "jail.local"
    assert "maxretry = 5" in change["before"] and "maxretry = 3" in change["after"]
    assert all("writable" not in call for call in host)
    refused = client.post(
        "/api/host/fail2ban/plan", json={"changes": [{"name": "sshd", "delete": True}]}
    )
    assert refused.status_code == 400


def test_api_apply_writes_through_a_job(
    client: TestClient,
    host: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
) -> None:
    submitted: list[Any] = []
    monkeypatch.setattr(
        job_service, "submit", lambda kind, label, runner: submitted.append(runner) or _job()
    )
    monkeypatch.setattr("app.core.config.settings.data_path", tmp_path)

    response = client.post(
        "/api/host/fail2ban/apply", json={"changes": [{"name": "sshd", "maxretry": "3"}]}
    )
    assert response.status_code == 202
    submitted[0](_Context())

    write = host[-1]
    assert write["writable"] == ("/etc/fail2ban",)
    assert write["environment"]["TOUCHED"] == "jail.local"
    assert "fail2ban-client -t" in write["script"]
    archive = base64.b64decode(write["environment"]["DRYDOCK_FILES"])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        assert tar.getnames() == ["jail.local"]
    backups = list((tmp_path / "backups" / "fail2ban").glob("*/jail.local"))
    assert [path.read_text() for path in backups] == [FILES["jail.local"]]


def test_api_is_admin_only() -> None:
    app.dependency_overrides[get_current_user] = lambda: type("U", (), {"is_admin": False})()
    app.dependency_overrides[get_db] = lambda: None
    try:
        response = TestClient(app).get("/api/host/fail2ban/jails")
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
        "label": "Apply fail2ban changes",
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
