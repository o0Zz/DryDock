"""fail2ban jails that DryDock manages, against the reverse proxy's access log.

fail2ban runs on the host, not in a container: its bans go into the host's nftables,
before Docker forwards anything. DryDock owns one jail file,
`/etc/fail2ban/jail.d/drydock.local`, and one filter per jail, `filter.d/drydock-<name>.conf`;
the rest of the host's fail2ban (sshd...) is never touched. The config lives in DryDock's
settings and the files are rendered from it.

Nothing names a proxy: the rules match an access log format. `text` is the line Traefik
and nginx (SWAG) write, `<ip> - <user> [<date>] "<request>" <status> <size> "<referer>"
"<agent>" ...`; `json` is Caddy's. Switching proxy means pointing at its log and format.

Bans go in an nftables chain on the forward hook (`f2b-docker`): the proxy's ports are
published by Docker, so its traffic is forwarded to the container and the input hook of
fail2ban's default action never sees it.
"""

from __future__ import annotations

import base64
import io
import re
import shlex
import tarfile
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.schemas.fail2ban import (
    Fail2banConfig,
    Fail2banHit,
    Fail2banJailConfig,
    Fail2banTestResult,
)
from app.services import docker_service, settings_service, volume_files_service

CONFIG_DIR = "/etc/fail2ban"
JAIL_FILE = "jail.d/drydock.local"
FILTER_PREFIX = "drydock-"
SETTING = "fail2ban_config"
# Lines read from the end of the log by a test: enough to judge a rule, cheap on a Pi.
TEST_LINES = 5000
TEST_SAMPLES = 20

DEFAULT_CONFIG: dict[str, Any] = {
    "log_path": "/data/proxy/logs/access.log",
    "log_format": "text",
    "allowlist_file": "/data/proxy/allowlist.txt",
    "ignore_ips": ["127.0.0.1/8", "::1", "192.168.0.0/16", "10.0.0.0/8", "172.16.0.0/12"],
    "ban_hook": "forward",
    "jails": [
        {"name": "auth", "rule": "auth", "maxretry": 3},
        {"name": "botsearch", "rule": "botsearch", "maxretry": 2},
        {"name": "badbots", "rule": "badbots", "maxretry": 2},
        {"name": "forbidden", "rule": "forbidden", "maxretry": 5},
    ],
}

# The request part of a `text` line, the date already cut out by fail2ban.
_TEXT = r'^<HOST> \S+ \S+ \[\] "'
# rule -> (filter to include for its variables, {format: failregex})
PRESETS: dict[str, tuple[str | None, dict[str, str]]] = {
    "auth": (
        None,
        {
            "text": _TEXT + r'[A-Z]+ [^"]*" 401 ',
            "json": r'"client_ip":"<HOST>".*"status":401\b',
        },
    ),
    "forbidden": (
        None,
        {
            "text": _TEXT + r'[A-Z]+ [^"]*" 403 ',
            "json": r'"client_ip":"<HOST>".*"status":403\b',
        },
    ),
    "botsearch": (
        "botsearch-common.conf",
        {
            "text": _TEXT + r'(?:GET|POST|HEAD) /<block> [^"]*" 404 ',
            "json": r'"client_ip":"<HOST>".*"uri":"/<block>[^"]*".*"status":404\b',
        },
    ),
    "badbots": (
        "apache-badbots.conf",
        {
            "text": _TEXT + r'[A-Z]+ [^"]*" \d+ \d+ "[^"]*" "(?:%(badbots)s|%(badbotscustom)s)"',
            "json": r'"client_ip":"<HOST>".*"User-Agent":\["(?:%(badbots)s|%(badbotscustom)s)',
        },
    ),
}
# Caddy logs an epoch timestamp.
_DATEPATTERN = {"json": '"ts":{EPOCH}'}

_JSON_IP = re.compile(r'"client_ip":"([^"]+)"')
_SUMMARY = re.compile(r"^Lines: (\d+) lines, \d+ ignored, (\d+) matched", re.MULTILINE)


class Fail2banConfigError(Exception):
    """fail2ban refused the config, or could not run on the host."""


def get_config(db: Session) -> Fail2banConfig:
    stored = settings_service.get_all(db).get(SETTING) or DEFAULT_CONFIG
    return Fail2banConfig.model_validate(stored)


def save_config(db: Session, config: Fail2banConfig) -> None:
    settings_service.set_many(db, {SETTING: config.model_dump()})


# --- Rendering ------------------------------------------------------------------------


def filter_name(jail: Fail2banJailConfig) -> str:
    return f"{FILTER_PREFIX}{jail.name}"


def render_filter(jail: Fail2banJailConfig, log_format: str, *, include_dir: str = "") -> str:
    """A filter file. `include_dir` makes the include absolute, for a filter outside filter.d."""
    if jail.rule == "custom":
        include, failregex = None, jail.failregex
    else:
        include, regexes = PRESETS[jail.rule]
        failregex = regexes[log_format]
    lines = [f"# Managed by DryDock: rule {jail.rule}, {log_format} access log."]
    if include:
        lines += ["[INCLUDES]", f"before = {include_dir}{include}", ""]
    lines += ["[Definition]", f"failregex = {failregex}", "ignoreregex ="]
    if log_format in _DATEPATTERN:
        lines.append(f"datepattern = {_DATEPATTERN[log_format]}")
    return "\n".join(lines) + "\n"


def render_jails(config: Fail2banConfig) -> str:
    if config.ban_hook == "forward":
        ban = (
            "banaction     = nftables[type=allports, chain_hook=forward]\n"
            "chain         = f2b-docker"
        )
    else:
        ban = "banaction     = nftables[type=allports]"
    sections = [
        "# Managed by DryDock (Host page, fail2ban). Edits here are overwritten.\n"
        f"# Proxy access log: {config.log_path} ({config.log_format})."
    ]
    for jail in config.jails:
        lines = [
            f"[{filter_name(jail)}]",
            f"enabled       = {'true' if jail.enabled else 'false'}",
            f"filter        = {filter_name(jail)}",
            f"logpath       = {config.log_path}",
            ban,
            f"maxretry      = {jail.maxretry}",
            f"findtime      = {jail.findtime}",
            f"bantime       = {jail.bantime}",
        ]
        if config.ignore_ips:
            lines.append(f"ignoreip      = {' '.join(config.ignore_ips)}")
        if config.allowlist_file:
            # The current public IP and trusted IPs: never ban yourself through the VPN.
            lines.append(f"ignorecommand = grep -qsxF <ip> {shlex.quote(config.allowlist_file)}")
        sections.append("\n".join(lines))
    return "\n\n".join(sections) + "\n"


def render(config: Fail2banConfig) -> dict[str, str]:
    """Every file DryDock owns, as path under /etc/fail2ban -> content."""
    files = {JAIL_FILE: render_jails(config)}
    for jail in config.jails:
        files[f"filter.d/{filter_name(jail)}.conf"] = render_filter(jail, config.log_format)
    return files


def _tar(files: dict[str, str]) -> str:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as tar:
        for path, content in files.items():
            data = content.encode("utf-8")
            info = tarfile.TarInfo(path)
            info.size = len(data)
            info.mode = 0o644
            tar.addfile(info, io.BytesIO(data))
    return base64.b64encode(buffer.getvalue()).decode("ascii")


# --- Host -----------------------------------------------------------------------------


def applied(config: Fail2banConfig) -> bool | None:
    """Whether the host's jail file is the one `config` renders; None when unreadable."""
    try:
        current = docker_service.read_host_file(
            f"{CONFIG_DIR}/{JAIL_FILE}", image=volume_files_service.helper_image()
        )
    except docker_service.DockerNotFound:
        return False
    except docker_service.DockerUnavailable:
        return None
    return current.decode("utf-8", errors="replace") == render_jails(config)


# Swaps DryDock's files, checks the whole config with `fail2ban-client -t`, puts the
# previous files back if it fails, then reloads. Errors go to stderr: that is what a
# failed helper reports.
_APPLY = r"""
set -e
cd /etc/fail2ban
fail() { echo "$1" >&2; exit 2; }
command -v fail2ban-client >/dev/null || fail "fail2ban is not installed on the host"
[ -e "$LOG_PATH" ] || fail "The access log $LOG_PATH does not exist on the host"
backup=/etc/fail2ban/.drydock-backup
rm -rf "$backup"; mkdir -p "$backup/jail.d" "$backup/filter.d"
cp -p jail.d/drydock.local "$backup/jail.d/" 2>/dev/null || true
cp -p filter.d/drydock-*.conf "$backup/filter.d/" 2>/dev/null || true
rm -f jail.d/drydock.local filter.d/drydock-*.conf
echo "$DRYDOCK_FILES" | base64 -d | tar -x -C /etc/fail2ban --no-same-owner
if ! out=$(fail2ban-client -t 2>&1); then
  rm -f jail.d/drydock.local filter.d/drydock-*.conf
  cp -p "$backup"/jail.d/* jail.d/ 2>/dev/null || true
  cp -p "$backup"/filter.d/* filter.d/ 2>/dev/null || true
  rm -rf "$backup"
  echo "fail2ban refused the config, the previous one is back:" >&2
  echo "$out" | tail -n 20 >&2
  exit 3
fi
rm -rf "$backup"
fail2ban-client reload
fail2ban-client status
"""


def apply(config: Fail2banConfig) -> str:
    """Write the jails and filters on the host and reload fail2ban. Returns its output."""
    try:
        return docker_service.run_on_host(
            _APPLY,
            image=volume_files_service.helper_image(),
            writable=(CONFIG_DIR,),
            environment={"DRYDOCK_FILES": _tar(render(config)), "LOG_PATH": config.log_path},
        )
    except docker_service.HostCommandFailed as exc:
        raise Fail2banConfigError(str(exc)) from exc


_TEST = r"""
set -e
[ -e "$LOG_PATH" ] || { echo "The access log $LOG_PATH does not exist on the host" >&2; exit 2; }
dir=$(mktemp -d /tmp/drydock-f2b.XXXXXX)
trap 'rm -rf "$dir"' EXIT
tail -n "$TEST_LINES" "$LOG_PATH" > "$dir/access.log"
echo "$DRYDOCK_FILTER" | base64 -d > "$dir/filter.conf"
fail2ban-regex --print-all-matched "$dir/access.log" "$dir/filter.conf"
"""


def test(config: Fail2banConfig, jail: Fail2banJailConfig) -> Fail2banTestResult:
    """Run a jail's rule over the end of the log with the host's fail2ban-regex."""
    # The filter sits in a temp folder, so its include needs the full path.
    rendered = render_filter(jail, config.log_format, include_dir=f"{CONFIG_DIR}/filter.d/")
    try:
        output = docker_service.run_on_host(
            _TEST,
            image=volume_files_service.helper_image(),
            writable=("/tmp",),
            environment={
                "LOG_PATH": config.log_path,
                "TEST_LINES": str(TEST_LINES),
                "DRYDOCK_FILTER": base64.b64encode(rendered.encode("utf-8")).decode("ascii"),
            },
        )
    except docker_service.HostCommandFailed as exc:
        raise Fail2banConfigError(str(exc)) from exc
    return parse_test(output, config.log_format)


def parse_test(output: str, log_format: str) -> Fail2banTestResult:
    summary = _SUMMARY.search(output)
    if summary is None:
        raise Fail2banConfigError(f"Unexpected fail2ban-regex output: {output[-500:]}")
    matched_lines: list[str] = []
    in_matched = False
    for line in output.splitlines():
        if line.startswith("|- Matched line(s):"):
            in_matched = True
        elif in_matched and line.startswith("|  "):
            matched_lines.append(line[3:].strip())
        elif in_matched:
            in_matched = False
    ips: Counter[str] = Counter()
    for line in matched_lines:
        if log_format == "json":
            found = _JSON_IP.search(line)
            ip = found.group(1) if found else None
        else:
            ip = line.split(" ", 1)[0] or None
        if ip:
            ips[ip] += 1
    return Fail2banTestResult(
        lines=int(summary.group(1)),
        matched=int(summary.group(2)),
        top_ips=[Fail2banHit(ip=ip, count=count) for ip, count in ips.most_common(10)],
        samples=matched_lines[-TEST_SAMPLES:],
    )
