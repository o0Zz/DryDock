"""fail2ban's jails, read from the host's files and changed in place.

The host's files are the only source of truth: DryDock keeps no copy of them. A
`Snapshot` holds the files under /etc/fail2ban and the output of `fail2ban-client -d`,
which is what fail2ban itself makes of them. Everything here is pure: reading a snapshot
into jails, and turning edits into new file contents. fail2ban_config_service does the
host side.

Where an edit goes:
- A key already set in a `.local` file is changed there, in place.
- A key that comes from a package `.conf` file (jail.conf, jail.d/defaults-debian.conf,
  filter.d/sshd.conf) goes to its `.local` twin: `jail.local` for a jail key,
  `filter.d/<filter>.local` for a regex. apt owns the `.conf` files and replaces them.
- A jail DryDock created has its own pair, `jail.d/<name>.local` and
  `filter.d/<name>.conf`, both starting with MARKER.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field

from app.schemas.fail2ban import (
    JAIL_NAME,
    Fail2banEdit,
    Fail2banJailChange,
    Fail2banJailConfig,
    Fail2banTemplate,
)
from app.services import fail2ban_ini as ini

MARKER = "# Managed by DryDock"
# Older DryDock versions wrote every jail in this one file, as `[drydock-<name>]`.
LEGACY_FILE = "jail.d/drydock.local"
# Every path DryDock may write, relative to /etc/fail2ban.
_WRITABLE = re.compile(
    r"^(?:jail\.local|jail\.d/[A-Za-z0-9_.-]+\.local|filter\.d/[A-Za-z0-9_.-]+\.(?:conf|local))$"
)
_SPECIAL = {"DEFAULT", "INCLUDES", "Definition", "Init"}

JAIL_KEYS = ("enabled", "logpath", "maxretry", "findtime", "bantime")
FILTER_KEYS = ("failregex", "ignoreregex")
# `fail2ban-client -d` option -> field.
_DUMP_FIELDS = {
    "addlogpath": "logpath",
    "addfailregex": "failregex",
    "addignoreregex": "ignoreregex",
    "maxretry": "maxretry",
    "findtime": "findtime",
    "bantime": "bantime",
}
_LIST_FIELDS = {"logpath", "failregex", "ignoreregex"}

# New jails watch the proxy's access log.
PROXY_LOG = "/data/proxy/logs/access.log"
_ALLOWLIST = "/data/proxy/allowlist.txt"
_IGNORE_IPS = "127.0.0.1/8 ::1 192.168.0.0/16 10.0.0.0/8 172.16.0.0/12"
# The request part of a `text` access log line, the date already cut out by fail2ban.
_TEXT = r'^<HOST> \S+ \S+ \[\] "'
TEMPLATES: dict[str, Fail2banTemplate] = {
    "auth": Fail2banTemplate(
        failregex={
            "text": _TEXT + r'[A-Z]+ [^"]*" 401 ',
            "json": r'"client_ip":"<HOST>".*"status":401\b',
        }
    ),
    "forbidden": Fail2banTemplate(
        failregex={
            "text": _TEXT + r'[A-Z]+ [^"]*" 403 ',
            "json": r'"client_ip":"<HOST>".*"status":403\b',
        }
    ),
    "botsearch": Fail2banTemplate(
        before="botsearch-common.conf",
        failregex={
            "text": _TEXT + r'(?:GET|POST|HEAD) /<block> [^"]*" 404 ',
            "json": r'"client_ip":"<HOST>".*"uri":"/<block>[^"]*".*"status":404\b',
        },
    ),
    "badbots": Fail2banTemplate(
        before="apache-badbots.conf",
        failregex={
            "text": _TEXT + r'[A-Z]+ [^"]*" \d+ \d+ "[^"]*" "(?:%(badbots)s|%(badbotscustom)s)"',
            "json": r'"client_ip":"<HOST>".*"User-Agent":\["(?:%(badbots)s|%(badbotscustom)s)',
        },
    ),
    "custom": Fail2banTemplate(failregex={"text": "", "json": ""}),
}
# Caddy logs an epoch timestamp.
_DATEPATTERN = {"json": '"ts":{EPOCH}'}
# A failregex line needs a tag fail2ban reads the client from.
_HOST_TAG = re.compile(r"<(?:HOST|ADDR|IP4|IP6|CIDR|SUBNET|F-ID)>")


class Fail2banPlanError(ValueError):
    """An edit DryDock refuses: unknown jail, name taken, a file apt owns."""


@dataclass
class Snapshot:
    # Path under /etc/fail2ban -> content.
    files: dict[str, str]
    # `fail2ban-client -d`: one Python list per line, `['set', 'sshd', 'maxretry', 5]`.
    dump: str = ""


@dataclass
class _Running:
    backend: str
    values: dict[str, list[str]] = field(default_factory=dict)
    lines: list[str] = field(default_factory=list)


# --- Reading ----------------------------------------------------------------------------


def _running(dump: str) -> dict[str, _Running]:
    """The jails in the dump, which lists only the enabled ones."""
    jails: dict[str, _Running] = {}
    for raw in dump.splitlines():
        line = raw.strip()
        try:
            command = ast.literal_eval(line)
        except (ValueError, SyntaxError):
            continue
        if not isinstance(command, list) or len(command) < 2 or not isinstance(command[1], str):
            continue
        verb, name = command[0], command[1]
        if verb == "add" and len(command) > 2:
            jails[name] = _Running(backend=str(command[2]))
        jail = jails.get(name)
        if jail is None:
            continue
        jail.lines.append(line)
        option = command[2] if len(command) > 3 else None
        key = _DUMP_FIELDS.get(option) if isinstance(option, str) else None
        if verb in ("set", "multi-set") and key:
            value = command[3]
            items = [str(item) for item in value] if verb == "multi-set" else [str(value)]
            jail.values[key] = jail.values.get(key, []) + items if key in _LIST_FIELDS else items
    return jails


def jail_paths(files: dict[str, str]) -> list[str]:
    """The jail files in the order fail2ban reads them: the last setting wins."""
    in_dir = sorted(path for path in files if path.startswith("jail.d/"))
    order = [
        "jail.conf",
        *(path for path in in_dir if path.endswith(".conf")),
        "jail.local",
        *(path for path in in_dir if path.endswith(".local")),
    ]
    return [path for path in order if path in files]


def _last(
    files: dict[str, str], paths: list[str], section: str, key: str
) -> tuple[list[str], str, int] | None:
    """(value, path, line) of the last file that sets `key` in `section`."""
    found = None
    for path in paths:
        line = ini.find(files[path], section, key)
        if line is not None:
            found = (ini.get(files[path], section, key) or [], path, line)
    return found


def _jail_value(files: dict[str, str], name: str, key: str) -> tuple[list[str], str, int] | None:
    paths = jail_paths(files)
    return _last(files, paths, name, key) or _last(files, paths, "DEFAULT", key)


def _filter_paths(files: dict[str, str], filter_name: str) -> list[str]:
    paths = [f"filter.d/{filter_name}.conf", f"filter.d/{filter_name}.local"]
    return [path for path in paths if path in files]


def filter_name(files: dict[str, str], name: str) -> str | None:
    """The filter.d file a jail uses: `filter = sshd[mode=aggressive]` gives `sshd`."""
    found = _jail_value(files, name, "filter")
    value = found[0][0] if found and found[0] else ""
    value = re.sub(r"\[.*\]$", "", value.replace("%(__name__)s", name)).strip()
    return value if re.fullmatch(JAIL_NAME, value) else None


def managed(files: dict[str, str], name: str) -> bool:
    return files.get(f"jail.d/{name}.local", "").startswith(MARKER)


def _names(files: dict[str, str], running: dict[str, _Running]) -> set[str]:
    """Enabled jails, jails DryDock created, and jails a `.local` file turns on or off."""
    names = set(running)
    for path in jail_paths(files):
        if not path.endswith(".local"):
            continue
        for section in ini.sections(files[path]):
            own = path == f"jail.d/{section}.local" and managed(files, section)
            if own or ini.find(files[path], section, "enabled"):
                names.add(section)
    return names - _SPECIAL


def read_jails(snapshot: Snapshot) -> list[Fail2banJailConfig]:
    files = snapshot.files
    running = _running(snapshot.dump)
    jails = []
    for name in sorted(_names(files, running)):
        values: dict[str, list[str]] = {}
        sources: dict[str, str] = {}
        for key in JAIL_KEYS:
            found = _jail_value(files, name, key)
            if found:
                values[key], sources[key] = found[0], f"{found[1]}:{found[2]}"
        filter_ = filter_name(files, name)
        for key in FILTER_KEYS:
            found = (
                _last(files, _filter_paths(files, filter_), "Definition", key) if filter_ else None
            )
            if found:
                values[key], sources[key] = found[0], f"{found[1]}:{found[2]}"
        live = running.get(name)
        backend = _jail_value(files, name, "backend")
        if live:
            # What fail2ban makes of the files: interpolated, every layer merged. A key it
            # leaves out is not used, such as a logpath under the systemd backend.
            values.update({key: live.values.get(key, []) for key in _DUMP_FIELDS.values()})
        jails.append(
            Fail2banJailConfig(
                name=name,
                managed=managed(files, name),
                enabled=live is not None,
                backend=live.backend
                if live
                else (backend[0][0] if backend and backend[0] else None),
                filter=filter_,
                logpath=values.get("logpath", []),
                failregex=values.get("failregex", []),
                ignoreregex=values.get("ignoreregex", []),
                maxretry=" ".join(values.get("maxretry", [])),
                findtime=" ".join(values.get("findtime", [])),
                bantime=" ".join(values.get("bantime", [])),
                sources=sources,
                dump=live.lines if live else [],
            )
        )
    return jails


# --- Rendering a new jail ---------------------------------------------------------------


def render_filter(
    before: str | None,
    failregex: list[str],
    ignoreregex: list[str],
    log_format: str,
    *,
    include_dir: str = "",
) -> str:
    """A filter file. `include_dir` makes the include absolute, for a filter outside filter.d."""
    lines = [f"{MARKER}. Edited in place from the Proxy page."]
    if before:
        lines += ["[INCLUDES]", f"before = {include_dir}{before}", ""]
    lines += [
        "[Definition]",
        *ini.format_value("failregex", failregex),
        *ini.format_value("ignoreregex", ignoreregex),
    ]
    if log_format in _DATEPATTERN:
        lines.append(f"datepattern = {_DATEPATTERN[log_format]}")
    return "\n".join(lines) + "\n"


def _render_jail(change: Fail2banJailChange) -> str:
    assert change.create is not None
    forward = change.create.ban_hook == "forward"
    settings = {
        "enabled": ["false" if change.enabled is False else "true"],
        "filter": [change.name],
        "logpath": change.logpath or [PROXY_LOG],
        # Docker forwards the proxy's published ports: the input hook never sees them.
        "banaction": [f"nftables[type=allports{', chain_hook=forward' if forward else ''}]"],
        **({"chain": ["f2b-docker"]} if forward else {}),
        "maxretry": [change.maxretry or "5"],
        "findtime": [change.findtime or "600"],
        "bantime": [change.bantime or "86400"],
        "ignoreip": [_IGNORE_IPS],
        # The proxy sync's allowlist: the public IP and trusted IPs are never banned.
        "ignorecommand": [f"grep -qsxF <ip> {_ALLOWLIST}"],
    }
    lines = [f"{MARKER}. Edited in place from the Proxy page.", f"[{change.name}]"]
    for key, values in settings.items():
        lines += ini.format_value(key, values)
    return "\n".join(lines) + "\n"


# --- Planning an edit -------------------------------------------------------------------


def _taken(files: dict[str, str], name: str) -> bool:
    if any(name in ini.sections(files[path]) for path in jail_paths(files)):
        return True
    paths = (f"jail.d/{name}.local", f"filter.d/{name}.conf", f"filter.d/{name}.local")
    return any(path in files for path in paths)


def _set(files: dict[str, str], path: str, section: str, key: str, values: list[str]) -> None:
    current = files.get(path)
    if current is None:
        # A new `.local` twin: say where it comes from.
        current = "# Written by DryDock's Proxy page. Values here win over the .conf files.\n"
    files[path] = ini.set_value(current, section, key, values)


def _jail_target(files: dict[str, str], name: str, key: str) -> str:
    found = _last(files, jail_paths(files), name, key)
    if found and found[1].endswith(".local"):
        return found[1]
    return f"jail.d/{name}.local" if managed(files, name) else "jail.local"


def _filter_target(files: dict[str, str], filter_: str, key: str) -> str:
    local, conf = f"filter.d/{filter_}.local", f"filter.d/{filter_}.conf"
    if ini.find(files.get(local, ""), "Definition", key):
        return local
    return conf if files.get(conf, "").startswith(MARKER) else local


def _check_regex(name: str, failregex: list[str]) -> None:
    if not failregex or not all(_HOST_TAG.search(line) for line in failregex):
        raise Fail2banPlanError(f"{name}: each failregex line needs <HOST>")


def _create(files: dict[str, str], change: Fail2banJailChange) -> None:
    assert change.create is not None
    template = TEMPLATES.get(change.create.template)
    if template is None:
        raise Fail2banPlanError(f"unknown template: {change.create.template}")
    if _taken(files, change.name):
        raise Fail2banPlanError(f"{change.name} is taken: a jail or a filter has that name")
    _check_regex(change.name, change.failregex or [])
    files[f"jail.d/{change.name}.local"] = _render_jail(change)
    files[f"filter.d/{change.name}.conf"] = render_filter(
        template.before, change.failregex or [], change.ignoreregex or [], change.create.log_format
    )


def _delete(files: dict[str, str], name: str) -> None:
    if not managed(files, name):
        raise Fail2banPlanError(f"{name} was not created by DryDock: turn it off instead")
    del files[f"jail.d/{name}.local"]
    if files.get(f"filter.d/{name}.conf", "").startswith(MARKER):
        del files[f"filter.d/{name}.conf"]


def _update(files: dict[str, str], change: Fail2banJailChange) -> None:
    name = change.name
    if not any(name in ini.sections(files[path]) for path in jail_paths(files)):
        raise Fail2banPlanError(f"no jail named {name}")
    for key in JAIL_KEYS:
        value = getattr(change, key)
        if value is not None:
            if isinstance(value, bool):
                value = "true" if value else "false"
            _set(files, _jail_target(files, name, key), name, key, _as_list(value))
    if change.failregex is None and change.ignoreregex is None:
        return
    filter_ = filter_name(files, name)
    if filter_ is None:
        raise Fail2banPlanError(f"{name}: DryDock cannot tell which filter this jail uses")
    if change.failregex is not None:
        _check_regex(name, change.failregex)
    for key in FILTER_KEYS:
        value = getattr(change, key)
        if value is not None:
            _set(files, _filter_target(files, filter_, key), "Definition", key, value)


def _as_list(value: str | list[str]) -> list[str]:
    return value if isinstance(value, list) else [value]


def _convert_legacy(files: dict[str, str]) -> None:
    """One file pair per jail out of `jail.d/drydock.local`: `[drydock-auth]` becomes `auth`."""
    legacy = files.pop(LEGACY_FILE, None)
    if legacy is None:
        return
    for old in ini.sections(legacy):
        new = old.removeprefix("drydock-")
        if new == old or _taken(files, new):
            new = old
        lines = [f"{MARKER}. Edited in place from the Proxy page.", f"[{new}]"]
        text = "\n".join([*lines, *ini.section_body(legacy, old)]) + "\n"
        files[f"jail.d/{new}.local"] = ini.set_value(text, new, "filter", [new])
        old_filter = files.pop(f"filter.d/{old}.conf", None)
        if old_filter is not None:
            files[f"filter.d/{new}.conf"] = old_filter


def plan(snapshot: Snapshot, edit: Fail2banEdit) -> dict[str, str | None]:
    """The files an edit changes: path -> new content, None to remove it."""
    files = dict(snapshot.files)
    if edit.convert_legacy:
        _convert_legacy(files)
    for change in edit.changes:
        if change.create:
            _create(files, change)
        elif change.delete:
            _delete(files, change.name)
        else:
            _update(files, change)
    changed = {
        path: files.get(path)
        for path in sorted(set(files) | set(snapshot.files))
        if files.get(path) != snapshot.files.get(path)
    }
    for path in changed:
        before = snapshot.files.get(path)
        if not _WRITABLE.match(path) or (
            path.endswith(".conf") and before is not None and not before.startswith(MARKER)
        ):
            raise Fail2banPlanError(
                f"DryDock never writes {path}: it belongs to the fail2ban package"
            )
    return changed
