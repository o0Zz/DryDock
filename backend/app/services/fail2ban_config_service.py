"""The host side of fail2ban's config: read it, write it, test a rule.

fail2ban runs on the host, not in a container: its bans go into the host's nftables,
before Docker forwards anything. Each call is one host helper (`run_on_host`): the
host's own fail2ban-client and fail2ban-regex run on the host's own files.
fail2ban_jails decides what to write; this module only moves files.

Bans of the proxy's jails go in an nftables chain on the forward hook (`f2b-docker`):
the proxy's ports are published by Docker, so its traffic is forwarded to the container
and the input hook of fail2ban's default action never sees it.
"""

from __future__ import annotations

import base64
import gzip
import io
import re
import tarfile
from collections import Counter
from datetime import UTC, datetime

from app.core.config import settings
from app.schemas.fail2ban import Fail2banHit, Fail2banTestRequest, Fail2banTestResult
from app.services import docker_service, fail2ban_jails, volume_files_service
from app.services.fail2ban_jails import Snapshot

CONFIG_DIR = "/etc/fail2ban"
# Lines read from the end of the log by a test: enough to judge a rule, cheap on a Pi.
TEST_LINES = 5000
TEST_SAMPLES = 20

_JSON_IP = re.compile(r'"client_ip":"([^"]+)"')
_SUMMARY = re.compile(r"^Lines: (\d+) lines, \d+ ignored, (\d+) matched", re.MULTILINE)
_FILES_MARK = "--DRYDOCK-FILES--"


class Fail2banConfigError(Exception):
    """fail2ban refused the config, or could not run on the host."""


def _run(script: str, **kwargs: object) -> str:
    try:
        return docker_service.run_on_host(
            script, image=volume_files_service.helper_image(), **kwargs
        )
    except docker_service.HostCommandFailed as exc:
        raise Fail2banConfigError(str(exc)) from exc


# `-d` reads the config and prints the commands it would give the server: what fail2ban
# makes of every file, interpolated. Then the jail and filter files, as a tar. action.d
# is left out: DryDock never reads it.
_READ = rf"""
set -e
if ! command -v fail2ban-client >/dev/null; then
  echo "fail2ban is not installed on the host" >&2; exit 2
fi
cd {CONFIG_DIR}
if ! dump=$(fail2ban-client -d 2>&1); then
  echo "fail2ban-client -d failed:" >&2; echo "$dump" | tail -n 20 >&2; exit 3
fi
printf '%s\n' "$dump"
echo "{_FILES_MARK}"
tar -cf - $(ls -d jail.conf jail.local jail.d filter.d 2>/dev/null) | gzip | base64 -w0
"""


def snapshot() -> Snapshot:
    output = _run(_READ)
    dump, _, encoded = output.partition(_FILES_MARK)
    files: dict[str, str] = {}
    with tarfile.open(
        fileobj=io.BytesIO(gzip.decompress(base64.b64decode(encoded.strip())))
    ) as tar:
        for member in tar:
            source = tar.extractfile(member) if member.isfile() else None
            if source is not None:
                text = source.read().decode("utf-8", errors="replace")
                files[member.name.removeprefix("./")] = text.replace("\r\n", "\n")
    return Snapshot(files=files, dump=dump)


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


def backup(snapshot_: Snapshot, changes: dict[str, str | None]) -> None:
    """Keep the files an apply is about to change, under <data>/backups/fail2ban/<stamp>/."""
    folder = settings.backups_path / "fail2ban" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    for path in changes:
        if path in snapshot_.files:
            target = folder / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(snapshot_.files[path], encoding="utf-8")


# Writes and removes the planned files, checks the whole config with `fail2ban-client -t`,
# puts every touched file back if it fails, then reloads. Paths are checked by
# fail2ban_jails (no spaces, no `..`). Errors go to stderr: that is what a failed helper
# reports.
_APPLY = rf"""
set -e
cd {CONFIG_DIR}
if ! command -v fail2ban-client >/dev/null; then
  echo "fail2ban is not installed on the host" >&2; exit 2
fi
backup=$(mktemp -d {CONFIG_DIR}/.drydock-backup.XXXXXX)
for path in $TOUCHED; do
  if [ -e "$path" ]; then mkdir -p "$backup/$(dirname "$path")"; cp -p "$path" "$backup/$path"; fi
done
restore() {{
  for path in $TOUCHED; do
    if [ -e "$backup/$path" ]; then cp -p "$backup/$path" "$path"; else rm -f "$path"; fi
  done
  rm -rf "$backup"
}}
[ -z "$DRYDOCK_FILES" ] || echo "$DRYDOCK_FILES" | base64 -d | tar -x --no-same-owner
for path in $REMOVED; do rm -f "$path"; done
if ! out=$(fail2ban-client -t 2>&1); then
  restore
  echo "fail2ban refused the config, the previous files are back:" >&2
  echo "$out" | tail -n 20 >&2
  exit 3
fi
rm -rf "$backup"
fail2ban-client reload
fail2ban-client status
"""


def apply(changes: dict[str, str | None]) -> str:
    """Write the planned files on the host and reload fail2ban. Returns its output."""
    written = {path: content for path, content in changes.items() if content is not None}
    return _run(
        _APPLY,
        writable=(CONFIG_DIR,),
        environment={
            "DRYDOCK_FILES": _tar(written) if written else "",
            "REMOVED": " ".join(path for path, content in changes.items() if content is None),
            "TOUCHED": " ".join(changes),
        },
    )


_TEST = r"""
set -e
[ -e "$LOG_PATH" ] || { echo "The log $LOG_PATH does not exist on the host" >&2; exit 2; }
dir=$(mktemp -d /tmp/drydock-f2b.XXXXXX)
trap 'rm -rf "$dir"' EXIT
tail -n "$TEST_LINES" "$LOG_PATH" > "$dir/access.log"
echo "$DRYDOCK_FILTER" | base64 -d > "$dir/filter.conf"
fail2ban-regex --print-all-matched "$dir/access.log" "$dir/filter.conf"
"""


def test(request: Fail2banTestRequest) -> Fail2banTestResult:
    """Run regexes over the end of a log with the host's fail2ban-regex.

    The test filter includes the jail's own filter, so its prefregex and datepattern
    apply, and replaces its regexes with the ones being edited.
    """
    if request.filter:
        before, log_format = f"{request.filter}.conf", ""
    else:
        template = fail2ban_jails.TEMPLATES.get(request.template or "custom")
        before, log_format = (template.before if template else None), request.log_format
    rendered = fail2ban_jails.render_filter(
        before,
        request.failregex,
        request.ignoreregex,
        log_format,
        include_dir=f"{CONFIG_DIR}/filter.d/",
    )
    output = _run(
        _TEST,
        writable=("/tmp",),
        environment={
            "LOG_PATH": request.logpath,
            "TEST_LINES": str(TEST_LINES),
            "DRYDOCK_FILTER": base64.b64encode(rendered.encode("utf-8")).decode("ascii"),
        },
    )
    return parse_test(output)


def parse_test(output: str) -> Fail2banTestResult:
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
        # A JSON line (Caddy) names its client; a text line starts with it.
        found = _JSON_IP.search(line)
        ip = found.group(1) if found else (line.split(" ", 1)[0] or None)
        if ip:
            ips[ip] += 1
    return Fail2banTestResult(
        lines=int(summary.group(1)),
        matched=int(summary.group(2)),
        top_ips=[Fail2banHit(ip=ip, count=count) for ip, count in ips.most_common(10)],
        samples=matched_lines[-TEST_SAMPLES:],
    )
