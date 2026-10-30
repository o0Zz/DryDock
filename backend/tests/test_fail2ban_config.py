"""fail2ban's jails: reading the host's files, editing them in place, the host side, the routes."""

import base64
import gzip
import io
import re
import tarfile
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.security import get_current_user
from app.main import app
from app.schemas.fail2ban import (
    Fail2banEdit,
    Fail2banJailTarget,
    Fail2banNewJail,
    Fail2banTestRequest,
)
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


def _jail(name: str, snapshot: Snapshot | None = None) -> Any:
    jails = jails_service.read_jails(snapshot or _snapshot())
    return next(jail for jail in jails if jail.name == name)


# --- INI blocks -------------------------------------------------------------------------


def test_a_block_is_replaced_where_it_is() -> None:
    text = (
        "# mine\n[sshd]\nmaxretry = 5\n#bantime = 1h\n\n# The next jail.\n[other]\nmaxretry = 1\n"
    )

    # The comment paragraph after a blank line introduces [other]: not part of [sshd].
    assert ini.blocks(text, "sshd") == [(2, "[sshd]\nmaxretry = 5\n#bantime = 1h")]
    assert ini.replace_section(text, "sshd", "[sshd]\nmaxretry = 3\n") == text.replace(
        "maxretry = 5\n#bantime = 1h", "maxretry = 3"
    )
    assert ini.replace_section(text, "sshd", "") == (
        "# mine\n\n# The next jail.\n[other]\nmaxretry = 1\n"
    )
    assert ini.replace_section(text, "new", "[new]\nenabled = true").endswith(
        "maxretry = 1\n\n[new]\nenabled = true\n"
    )
    assert ini.get(text, "sshd", "maxretry") == ["5"]


# --- Reading ----------------------------------------------------------------------------


def test_sshd_shows_every_block_in_read_order() -> None:
    sshd = _jail("sshd")

    assert [(block.path, block.line, block.owner) for block in sshd.blocks] == [
        ("jail.conf", 10, "package"),
        ("jail.d/defaults-debian.conf", 4, "package"),
        ("jail.local", 1, "local"),
        ("filter.d/sshd.conf", None, "package"),
        # No override of the filter yet: where it would go.
        ("filter.d/sshd.local", None, "local"),
    ]
    assert sshd.blocks[2].text == FILES["jail.local"].rstrip("\n")
    assert sshd.blocks[-1].text == ""
    assert sshd.enabled and not sshd.managed
    assert (sshd.backend, sshd.filter) == ("systemd", "sshd")
    # jail.local sets a logpath, but the systemd backend reads the journal.
    assert sshd.logpath == []
    assert (sshd.maxretry, sshd.findtime, sshd.bantime) == ("5", "600", "86400")
    assert sshd.dump[0] == "['add', 'sshd', 'systemd']"
    # Not started, not touched by a .local file: not listed.
    assert "apache-badbots" not in [jail.name for jail in jails_service.read_jails(_snapshot())]


def test_a_disabled_jail_is_read_from_its_files() -> None:
    local = FILES["jail.local"].replace("enabled = true", "enabled = false")
    snapshot = _snapshot(**{"jail.local": local, "jail.d/defaults-debian.conf": None})
    snapshot.dump = ""

    sshd = _jail("sshd", snapshot)

    assert not sshd.enabled
    assert sshd.logpath == ["/var/log/auth.log"]
    assert sshd.backend == "%(sshd_backend)s"


def test_a_jail_only_in_package_files_gets_a_place_in_jail_local() -> None:
    sshd = _jail("sshd", _snapshot(**{"jail.local": None}))

    assert (sshd.blocks[2].path, sshd.blocks[2].text, sshd.blocks[2].owner) == (
        "jail.local",
        "",
        "local",
    )


# --- Editing ----------------------------------------------------------------------------


def test_a_block_goes_back_in_its_file() -> None:
    block = FILES["jail.local"].replace("maxretry = 5", "maxretry = 3")

    changes = _plan(files=[{"path": "jail.local", "section": "sshd", "text": block}])

    assert changes == {"jail.local": block}


def test_an_override_is_added_to_a_local_file() -> None:
    changes = _plan(
        _snapshot(**{"jail.local": "[DEFAULT]\nbantime = 1h\n"}),
        files=[{"path": "jail.local", "section": "sshd", "text": "[sshd]\nmaxretry = 3"}],
    )

    assert changes == {"jail.local": "[DEFAULT]\nbantime = 1h\n\n[sshd]\nmaxretry = 3\n"}


def test_a_filter_is_overridden_in_its_local_twin() -> None:
    text = "[Definition]\nfailregex = ^Failed \\S+ for <HOST>\n"

    changes = _plan(files=[{"path": "filter.d/sshd.local", "text": text}])

    assert changes == {"filter.d/sshd.local": text}


def test_package_files_and_stray_sections_are_refused() -> None:
    with pytest.raises(Fail2banPlanError, match="apt owns"):
        _plan(files=[{"path": "filter.d/sshd.conf", "text": "[Definition]\n"}])
    with pytest.raises(ValueError):  # jail.conf is not even a writable path
        _plan(files=[{"path": "jail.conf", "section": "sshd", "text": "[sshd]\n"}])
    for text in ("[sshd]\nmaxretry = 3\n[recidive]\nenabled = true", "maxretry = 3"):
        with pytest.raises(Fail2banPlanError, match=r"\[sshd\] section only"):
            _plan(files=[{"path": "jail.local", "section": "sshd", "text": text}])
    with pytest.raises(Fail2banPlanError, match="only removes"):
        _plan(files=[{"path": "jail.local", "text": None}])


# --- One file pair per jail -------------------------------------------------------------


def _new(name: str = "scanners", **fields: Any) -> list[dict[str, Any]]:
    new = Fail2banNewJail(name=name, template="botsearch", **fields)
    files = jails_service.render_new(new)
    return [{"path": path, "text": text, "new": True} for path, text in files.items()]


def test_a_new_jail_gets_its_own_files() -> None:
    changes = _plan(files=_new())

    jail, filter_ = changes["jail.d/scanners.local"] or "", changes["filter.d/scanners.conf"] or ""
    assert jail.startswith(jails_service.MARKER)
    assert ini.get(jail, "scanners", "filter") == ["scanners"]
    assert ini.get(jail, "scanners", "banaction") == ["nftables[type=allports, chain_hook=forward]"]
    assert "before = botsearch-common.conf" in filter_
    # The allowlist sits next to the log folder, wherever PROXY_DATA is.
    assert "ignorecommand = grep -qsxF <ip> /data/proxy/allowlist.txt" in jail
    moved = Fail2banNewJail(name="x", template="auth", logpath="/srv/p/logs/access.log")
    assert (
        "grep -qsxF <ip> /srv/p/allowlist.txt" in jails_service.render_new(moved)["jail.d/x.local"]
    )
    scanners = _jail("scanners", _snapshot(**changes))
    assert scanners.managed
    assert [block.owner for block in scanners.blocks] == ["drydock", "drydock"]
    # Shown before it exists like after: its jail section and its whole filter.
    shown = jails_service.new_jail(Fail2banNewJail(name="scanners", template="botsearch"))
    assert [block.path for block in shown.blocks] == [block.path for block in scanners.blocks]


def test_a_new_jail_needs_a_free_name() -> None:
    for name in ("sshd", "drydock-auth"):
        with pytest.raises(Fail2banPlanError, match="taken"):
            _plan(files=_new(name))


def test_only_drydocks_files_are_removed() -> None:
    snapshot = _snapshot(**_plan(files=_new()))

    removed = _plan(
        snapshot,
        files=[
            {"path": "jail.d/scanners.local", "text": None},
            {"path": "filter.d/scanners.conf", "text": None},
        ],
    )

    assert removed == {"filter.d/scanners.conf": None, "jail.d/scanners.local": None}


def test_reset_replaces_every_drydock_jail_with_the_default_set() -> None:
    # The old single file and a jail made from the UI both go; a user's drydock-* file stays.
    snapshot = _snapshot(
        **{
            "jail.d/drydock-forbidden.local": f"{jails_service.MARKER}\n[drydock-forbidden]\n",
            "filter.d/drydock-forbidden.conf": f"{jails_service.MARKER}\n[Definition]\n",
            "jail.d/drydock-mine.local": "[drydock-mine]\nenabled = true\n",
        }
    )

    edit = jails_service.default_edit(snapshot, Fail2banJailTarget(logpath="/srv/p/logs/a.log"))
    changes = jails_service.plan(snapshot, edit)

    assert [file.path for file in edit.files if file.text is None] == [
        "filter.d/drydock-auth.conf",
        "filter.d/drydock-forbidden.conf",
        "jail.d/drydock-forbidden.local",
        "jail.d/drydock.local",
    ]
    assert changes["jail.d/drydock.local"] is None
    assert "jail.d/drydock-mine.local" not in changes
    written = {path for path, text in changes.items() if text is not None}
    assert written == {
        f"{folder}/drydock-{name}.{ext}"
        for name in jails_service.DEFAULT_JAILS
        for folder, ext in (("jail.d", "local"), ("filter.d", "conf"))
    }
    assert "/srv/p/allowlist.txt" in (changes["jail.d/drydock-auth.local"] or "")
    names = [jail.name for jail in jails_service.read_jails(_snapshot(**changes))]
    assert names == sorted([f"drydock-{name}" for name in jails_service.DEFAULT_JAILS] + ["sshd"])


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


def test_a_test_runs_the_edited_filter(host: list[dict[str, Any]]) -> None:
    host_output["value"] = REGEX_OUTPUT
    edited = {"filter.d/sshd.local": "[Definition]\nfailregex = <HOST>\n", "jail.local": "x"}
    request = Fail2banTestRequest(logpath="/var/log/auth.log", filter="sshd", files=edited)

    result = fail2ban_config_service.test(request)

    environment = host[0]["environment"]
    assert environment["FILTER"] == "sshd"
    archive = base64.b64decode(environment["DRYDOCK_FILES"])
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        assert tar.getnames() == ["filter.d/sshd.local"]
    assert host[0]["writable"] == ("/tmp",)
    assert (result.lines, result.matched) == (3, 2)
    assert [(hit.ip, hit.count) for hit in result.top_ips] == [("203.0.113.5", 2)]


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
    assert read["jails"][1]["blocks"][2]["path"] == "jail.local"
    assert "botsearch" in read["templates"]


def test_api_renders_a_new_jail_without_writing(
    client: TestClient, host: list[dict[str, Any]]
) -> None:
    jail = client.post("/api/host/fail2ban/new", json={"name": "auth", "template": "auth"}).json()

    assert [block["path"] for block in jail["blocks"]] == [
        "jail.d/auth.local",
        "filter.d/auth.conf",
    ]
    assert host == []


def test_api_plans_without_writing(client: TestClient, host: list[dict[str, Any]]) -> None:
    block = FILES["jail.local"].replace("maxretry = 5", "maxretry = 3")
    edit = {"files": [{"path": "jail.local", "section": "sshd", "text": block}]}

    [change] = client.post("/api/host/fail2ban/plan", json=edit).json()["files"]

    assert change == {"path": "jail.local", "before": FILES["jail.local"], "after": block}
    assert all("writable" not in call for call in host)
    refused = {"files": [{"path": "filter.d/sshd.conf", "text": "x"}]}
    assert client.post("/api/host/fail2ban/plan", json=refused).status_code == 400


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
    block = FILES["jail.local"].replace("maxretry = 5", "maxretry = 3")

    response = client.post(
        "/api/host/fail2ban/apply",
        json={"files": [{"path": "jail.local", "section": "sshd", "text": block}]},
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


def test_unknown_host_template_matches_a_404_with_no_router() -> None:
    _, failregex = jails_service.TEMPLATES["unknownhost"]
    regex = re.compile(failregex.replace("<HOST>", r"(?P<host>\S+)"))
    # Traefik's CLF line, the date already cut out by fail2ban.
    no_route = '1.2.3.4 - - [] "GET / HTTP/2.0" 404 19 "-" "curl/8.0" 7 "-" "-" 0ms'
    routed = '1.2.3.4 - - [] "GET /x HTTP/2.0" 404 19 "-" "curl" 8 "app@file" "http://app" 3ms'

    match = regex.search(no_route)
    assert match and match.group("host") == "1.2.3.4"
    assert regex.search(routed) is None
