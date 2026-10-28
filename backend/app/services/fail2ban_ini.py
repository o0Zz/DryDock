"""Line-level reading and editing of fail2ban's INI files.

fail2ban reads its files with Python's configparser, but writing them back with it would
drop every comment and reorder the file. These helpers touch only the lines of one key,
so a hand-written jail.local stays as its owner wrote it.

Same rules as configparser: `[section]` at the start of a line, `key = value` or
`key: value`, keys are case-insensitive, an indented line continues the value above it,
and when a key is set twice the last one wins.
"""

from __future__ import annotations

import re

_SECTION = re.compile(r"^\[([^\]]+)\]")
_KEY = re.compile(r"^([^\s#;\[=:][^=:]*?)\s*[=:]\s*(.*)$")


def _sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """(name, header line, end line exclusive) of every section, in order."""
    headers = [
        (match.group(1).strip(), at)
        for at, line in enumerate(lines)
        if (match := _SECTION.match(line))
    ]
    ends = [at for _, at in headers[1:]] + [len(lines)] * bool(headers)
    return [(name, at, end) for (name, at), end in zip(headers, ends, strict=True)]


def _continues(line: str) -> bool:
    return not line.strip() or line[0] in " \t"


def _span(lines: list[str], section: str, key: str) -> tuple[int, int] | None:
    """Lines [start, end) of the last `key` of `section`: its line and continuations."""
    found = None
    for name, header, end in _sections(lines):
        if name != section:
            continue
        at = header + 1
        while at < end:
            match = _KEY.match(lines[at])
            if not match or match.group(1).strip().lower() != key:
                at += 1
                continue
            stop = at + 1
            while stop < end and _continues(lines[stop]):
                stop += 1
            while stop > at + 1 and not lines[stop - 1].strip():
                stop -= 1
            found = (at, stop)
            at = stop
    return found


def sections(text: str) -> list[str]:
    return [name for name, _, _ in _sections(text.split("\n"))]


def section_body(text: str, section: str) -> list[str]:
    """The lines under the first `[section]`, without the trailing blank ones."""
    lines = text.split("\n")
    for name, header, end in _sections(lines):
        if name == section:
            body = lines[header + 1 : end]
            while body and not body[-1].strip():
                body.pop()
            return body
    return []


def find(text: str, section: str, key: str) -> int | None:
    """1-based line of the last `key` in `section`, or None."""
    span = _span(text.split("\n"), section, key)
    return span[0] + 1 if span else None


def get(text: str, section: str, key: str) -> list[str] | None:
    """The value of `key` in `section`, one item per non-empty line, or None when unset."""
    lines = text.split("\n")
    span = _span(lines, section, key)
    if span is None:
        return None
    match = _KEY.match(lines[span[0]])
    assert match is not None
    values = [match.group(2).strip(), *(line.strip() for line in lines[span[0] + 1 : span[1]])]
    return [value for value in values if value and not value.startswith(("#", ";"))]


def format_value(key: str, values: list[str]) -> list[str]:
    """`key = first` and the next values indented under it, one per line."""
    if not values:
        return [f"{key} ="]
    indent = " " * (len(key) + 3)
    return [f"{key} = {values[0]}", *(indent + value for value in values[1:])]


def set_value(text: str, section: str, key: str, values: list[str] | None) -> str:
    """`text` with `key` of `section` set to `values`, or removed when None.

    An existing key is replaced where it is. A new key goes at the end of the section's
    last block, and a missing section is added at the end of the file.
    """
    lines = text.split("\n")
    span = _span(lines, section, key)
    new = [] if values is None else format_value(key, values)
    if span is not None:
        lines[span[0] : span[1]] = new
    elif values is None:
        return text
    else:
        blocks = [block for block in _sections(lines) if block[0] == section]
        if blocks:
            _, header, end = blocks[-1]
            while end > header + 1 and not lines[end - 1].strip():
                end -= 1
            lines[end:end] = new
        else:
            while lines and not lines[-1].strip():
                lines.pop()
            lines += [*([""] if lines else []), f"[{section}]", *new, ""]
    result = "\n".join(lines)
    return result if result.endswith("\n") else result + "\n"
