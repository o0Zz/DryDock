"""Line-level reading of fail2ban's INI files, and replacing one section's text.

fail2ban reads its files with Python's configparser, but writing them back with it would
drop every comment and reorder the file. DryDock edits a section as raw text instead: the
user sees the block as it is in the file, and the block is put back where it was.

Same rules as configparser: `[section]` at the start of a line, `key = value` or
`key: value`, keys are case-insensitive, an indented line continues the value above it,
and when a key is set twice the last one wins.
"""

from __future__ import annotations

import re

_SECTION = re.compile(r"^\[([^\]]+)\]")
_KEY = re.compile(r"^([^\s#;\[=:][^=:]*?)\s*[=:]\s*(.*)$")


def _sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """(name, header line, end of its text) of every section, in order.

    A block ends before the next header, without its trailing blank lines, and without a
    comment paragraph after a blank line: in jail.conf such a paragraph introduces the
    next section. Both stay in the file when a block is replaced.
    """
    headers = [
        (match.group(1).strip(), at)
        for at, line in enumerate(lines)
        if (match := _SECTION.match(line))
    ]
    found = []
    for index, (name, header) in enumerate(headers):
        last = index + 1 == len(headers)
        end = len(lines) if last else headers[index + 1][1]
        while True:
            while end > header + 1 and not lines[end - 1].strip():
                end -= 1
            start = end
            while start > header + 1 and lines[start - 1].startswith(("#", ";")):
                start -= 1
            if last or start == end or lines[start - 1].strip():
                break
            end = start
        found.append((name, header, end))
    return found


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
            while stop < end and (not lines[stop].strip() or lines[stop][0] in " \t"):
                stop += 1
            found = (at, stop)
            at = stop
    return found


def sections(text: str) -> list[str]:
    return [name for name, _, _ in _sections(text.split("\n"))]


def blocks(text: str, section: str) -> list[tuple[int, str]]:
    """(1-based header line, text) of each `[section]` block, header included."""
    lines = text.split("\n")
    return [
        (header + 1, "\n".join(lines[header:end]))
        for name, header, end in _sections(lines)
        if name == section
    ]


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


def replace_section(text: str, section: str, block: str) -> str:
    """`text` with its `[section]` block replaced by `block`, header included.

    The block goes where the first one was, and any later `[section]` of the file goes:
    one block per section. An empty `block` removes the section; a section the file does
    not have is added at its end.
    """
    lines = text.split("\n")
    new = block.strip("\n").split("\n") if block.strip() else []
    found = [(header, end) for name, header, end in _sections(lines) if name == section]
    if not found:
        if not new:
            return text
        while lines and not lines[-1].strip():
            lines.pop()
        lines += [*([""] if lines else []), *new]
    else:
        for header, end in reversed(found[1:]):
            del lines[header:end]
        header, end = found[0]
        lines[header:end] = new
    result = "\n".join(lines).rstrip("\n")
    return result + "\n" if result else ""
