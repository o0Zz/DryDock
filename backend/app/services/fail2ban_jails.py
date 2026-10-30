"""fail2ban's jails, read from the host's files and edited as raw text.

The host's files are the only source of truth: DryDock keeps no copy of them. A
`Snapshot` holds the files under /etc/fail2ban and the output of `fail2ban-client -d`,
which is what fail2ban itself makes of them. Everything here is pure: reading a snapshot
into jails, and turning edits into new file contents. fail2ban_config_service does the
host side.

A jail is shown as the blocks that define it, in the order fail2ban reads them: its
`[name]` section in each jail file, and its whole filter files. The user edits a block's
text, and the block goes back where it was. apt owns the `.conf` files, so they are read
only: a value from one is changed in its `.local` twin (`jail.local`,
`filter.d/<filter>.local`), which fail2ban reads after it. A jail DryDock creates has its
own pair, `jail.d/<name>.local` and `filter.d/<name>.conf`, both starting with MARKER.

The templates match Traefik's access log (common log format). The allowlist the proxy sync
writes sits next to the log folder (`PROXY_DATA/allowlist.txt`, `PROXY_DATA/logs/access.log`),
so a jail never bans the public IP or a trusted one.
"""

from __future__ import annotations

import ast
import posixpath
import re
from dataclasses import dataclass, field

from app.schemas.fail2ban import (
    JAIL_NAME,
    Fail2banBlock,
    Fail2banEdit,
    Fail2banFileEdit,
    Fail2banJailConfig,
    Fail2banJailTarget,
    Fail2banNewJail,
)
from app.services import fail2ban_ini as ini

MARKER = "# Managed by DryDock"
# The jail set for a reverse proxy's access log, one per template, named `drydock-<template>`.
DEFAULT_PREFIX = "drydock-"
DEFAULT_JAILS = ("auth", "forbidden", "botsearch", "badbots", "unknownhost")
# The files of that set, the single `jail.d/drydock.local` of older versions included.
_DEFAULT_FILE = re.compile(r"^(?:jail\.d/drydock(?:-[^/]+)?\.local|filter\.d/drydock-[^/]+\.conf)$")
_SPECIAL = {"DEFAULT", "INCLUDES", "Definition", "Init"}
# `fail2ban-client -d` option -> summary field.
_DUMP_FIELDS = {
    "addlogpath": "logpath",
    "maxretry": "maxretry",
    "findtime": "findtime",
    "bantime": "bantime",
}

# The request part of an access log line, the date already cut out by fail2ban.
_LINE = r'^<HOST> \S+ \S+ \[\] "'
# template -> (filter.d file to include for its variables, failregex)
TEMPLATES: dict[str, tuple[str | None, str]] = {
    "auth": (None, _LINE + r'[A-Z]+ [^"]*" 401 '),
    "forbidden": (None, _LINE + r'[A-Z]+ [^"]*" 403 '),
    "botsearch": ("botsearch-common.conf", _LINE + r'(?:GET|POST|HEAD) /<block> [^"]*" 404 '),
    "badbots": (
        "apache-badbots.conf",
        _LINE + r'[A-Z]+ [^"]*" \d+ \d+ "[^"]*" "(?:%(badbots)s|%(badbotscustom)s)"',
    ),
    # A name no route claims (a typo, or a scan of the wildcard DNS record). Traefik answers
    # 404 with no router, which its CLF log writes as `"-" "-"` after the request count;
    # a 404 from a service has its router there.
    "unknownhost": (None, _LINE + r'[A-Z]+ [^"]*" 404 \S+ "[^"]*" "[^"]*" \d+ "-" "-" '),
    # Matches only /change-me until edited: a bare <HOST> would ban every visitor.
    "custom": (None, _LINE + r'[A-Z]+ /change-me[^"]*" \d+ '),
}


class Fail2banPlanError(ValueError):
    """An edit DryDock refuses: a file apt owns, a name taken, a block out of its section."""


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
        if verb == "set" and key:
            jail.values[key] = jail.values.get(key, []) + [str(command[3])]
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


def _jail_value(files: dict[str, str], name: str, key: str) -> list[str]:
    """The last value of `key` for a jail, from its section or else [DEFAULT]."""
    paths = jail_paths(files)
    for section in (name, "DEFAULT"):
        found = [path for path in paths if ini.find(files[path], section, key)]
        if found:
            return ini.get(files[found[-1]], section, key) or []
    return []


def filter_name(files: dict[str, str], name: str) -> str | None:
    """The filter.d file a jail uses: `filter = sshd[mode=aggressive]` gives `sshd`."""
    value = next(iter(_jail_value(files, name, "filter")), "")
    value = re.sub(r"\[.*\]$", "", value.replace("%(__name__)s", name)).strip()
    return value if re.fullmatch(JAIL_NAME, value) else None


def managed(files: dict[str, str], name: str) -> bool:
    return files.get(f"jail.d/{name}.local", "").startswith(MARKER)


def _owner(path: str, text: str) -> str:
    if text.startswith(MARKER):
        return "drydock"
    return "package" if path.endswith(".conf") else "local"


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


def _blocks(files: dict[str, str], name: str, filter_: str | None) -> list[Fail2banBlock]:
    blocks = [
        Fail2banBlock(
            path=path, section=name, line=line, text=text, owner=_owner(path, files[path])
        )
        for path in jail_paths(files)
        for line, text in ini.blocks(files[path], name)
    ]
    if all(block.owner == "package" for block in blocks):
        # Where an override of the package's values goes.
        blocks.append(Fail2banBlock(path="jail.local", section=name, text="", owner="local"))
    if filter_ is None:
        return blocks
    paths = [f"filter.d/{filter_}.conf", f"filter.d/{filter_}.local"]
    filters = [
        Fail2banBlock(path=path, section=None, text=files[path], owner=_owner(path, files[path]))
        for path in paths
        if path in files
    ]
    if all(block.owner == "package" for block in filters):
        filters.append(Fail2banBlock(path=paths[1], section=None, text="", owner="local"))
    return blocks + filters


def read_jails(snapshot: Snapshot) -> list[Fail2banJailConfig]:
    files = snapshot.files
    running = _running(snapshot.dump)
    jails = []
    for name in sorted(_names(files, running)):
        live = running.get(name)
        filter_ = filter_name(files, name)

        def value(key: str, live: _Running | None = live, name: str = name) -> list[str]:
            # What fail2ban makes of the files when the jail is on: interpolated, every
            # layer merged. A key it leaves out is not used (a logpath under systemd).
            return live.values.get(key, []) if live else _jail_value(files, name, key)

        jails.append(
            Fail2banJailConfig(
                name=name,
                managed=managed(files, name),
                enabled=live is not None,
                backend=live.backend if live else next(iter(value("backend")), None),
                filter=filter_,
                logpath=value("logpath"),
                maxretry=" ".join(value("maxretry")),
                findtime=" ".join(value("findtime")),
                bantime=" ".join(value("bantime")),
                blocks=_blocks(files, name, filter_),
                dump=live.lines if live else [],
            )
        )
    return jails


# --- A new jail -------------------------------------------------------------------------


def render_new(new: Fail2banNewJail) -> dict[str, str]:
    """The two files of a new jail, as path -> text."""
    if new.template not in TEMPLATES:
        raise Fail2banPlanError(f"unknown template: {new.template}")
    before, failregex = TEMPLATES[new.template]
    # Docker forwards the proxy's published ports: the input hook never sees them.
    forward = new.ban_hook == "forward"
    banaction = f"nftables[type=allports{', chain_hook=forward' if forward else ''}]"
    allowlist = posixpath.join(posixpath.dirname(posixpath.dirname(new.logpath)), "allowlist.txt")
    jail = [
        f"{MARKER}. Edited in place from the Proxy page.",
        f"[{new.name}]",
        "enabled       = true",
        f"filter        = {new.name}",
        f"logpath       = {new.logpath}",
        f"banaction     = {banaction}",
        *(["chain         = f2b-docker"] if forward else []),
        "maxretry      = 5",
        "findtime      = 600",
        "bantime       = 86400",
        "ignoreip      = 127.0.0.1/8 ::1 192.168.0.0/16 10.0.0.0/8 172.16.0.0/12",
        # The proxy sync's allowlist: the public IP and trusted IPs are never banned.
        f"ignorecommand = grep -qsxF <ip> {allowlist}",
    ]
    filter_ = [
        f"{MARKER}. Edited in place from the Proxy page.",
        *(["[INCLUDES]", f"before = {before}", ""] if before else []),
        "[Definition]",
        f"failregex = {failregex}",
        "ignoreregex =",
    ]
    return {
        f"jail.d/{new.name}.local": "\n".join(jail) + "\n",
        f"filter.d/{new.name}.conf": "\n".join(filter_) + "\n",
    }


def new_jail(new: Fail2banNewJail) -> Fail2banJailConfig:
    """A jail not written yet, to edit before applying. Its files are shown whole, the
    MARKER line included: each one is written as a new file."""
    return Fail2banJailConfig(
        name=new.name,
        managed=True,
        enabled=True,
        filter=new.name,
        logpath=[new.logpath],
        blocks=[
            Fail2banBlock(path=path, section=None, text=text, owner="drydock")
            for path, text in render_new(new).items()
        ],
    )


def default_edit(snapshot: Snapshot, target: Fail2banJailTarget) -> Fail2banEdit:
    """The edit that resets the default set: every `drydock-*` file DryDock wrote goes,
    then the set is rendered again. A `drydock-*` file someone else wrote stays, and the
    plan then refuses the name as taken."""
    removed = [
        Fail2banFileEdit(path=path, text=None)
        for path, text in sorted(snapshot.files.items())
        if _DEFAULT_FILE.match(path) and text.startswith(MARKER)
    ]
    added = [
        Fail2banFileEdit(path=path, text=text, new=True)
        for template in DEFAULT_JAILS
        for path, text in render_new(
            Fail2banNewJail(
                name=f"{DEFAULT_PREFIX}{template}", template=template, **target.model_dump()
            )
        ).items()
    ]
    return Fail2banEdit(files=removed + added)


# --- Planning an edit -------------------------------------------------------------------


def _taken(files: dict[str, str], name: str) -> bool:
    if any(name in ini.sections(files[path]) for path in jail_paths(files)):
        return True
    paths = (f"jail.d/{name}.local", f"filter.d/{name}.conf", f"filter.d/{name}.local")
    return any(path in files for path in paths)


def plan(snapshot: Snapshot, edit: Fail2banEdit) -> dict[str, str | None]:
    """The files an edit changes: path -> new content, None to remove it."""
    files = dict(snapshot.files)
    for change in edit.files:
        current = files.get(change.path)
        if change.new:
            name = re.fullmatch(r"jail\.d/(.+)\.local", change.path)
            if current is not None or (name and _taken(files, name.group(1))):
                raise Fail2banPlanError(f"{change.path} is taken: a jail or a file has that name")
        if change.section is not None:
            block = change.text or ""
            if block.strip() and ini.sections(block) != [change.section]:
                raise Fail2banPlanError(
                    f"{change.path}: the block must be the [{change.section}] section only"
                )
            files[change.path] = ini.replace_section(current or "", change.section, block)
        elif change.text is not None:
            files[change.path] = change.text.rstrip("\n") + "\n"
        elif (current or "").startswith(MARKER):
            del files[change.path]
        else:
            raise Fail2banPlanError(f"DryDock only removes the files it created, not {change.path}")
    changed = {
        path: files.get(path)
        for path in sorted(set(files) | set(snapshot.files))
        if files.get(path) != snapshot.files.get(path)
    }
    for path, after in changed.items():
        texts = (snapshot.files.get(path), after)
        if path.endswith(".conf") and not all(t is None or t.startswith(MARKER) for t in texts):
            raise Fail2banPlanError(
                f"DryDock never writes {path}: apt owns it. Put the change in its .local twin."
            )
    return changed
