"""Latest commit of a git build context, for update checks on services built from git.

`build: https://github.com/me/app.git#main` makes Docker clone that ref at build
time, so no registry knows when it changes. The git smart HTTP protocol lists a
repo's refs in one request (what `git ls-remote` does), without cloning and
without a git binary. A private repo is read with the stored login for its host
(git_auth_service).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from app.services import git_auth_service

TIMEOUT = 20.0

_SHA = re.compile(r"^[0-9a-f]{40}$")


class GitError(Exception):
    """The repo could not be read: unsupported URL, private, missing ref, network."""


@dataclass(frozen=True)
class GitSource:
    url: str
    # Branch, tag or commit from the `#ref` fragment; None means the default branch.
    ref: str | None = None

    def __str__(self) -> str:
        return f"{self.url}#{self.ref}" if self.ref else self.url


def parse_build(build: object) -> GitSource | None:
    """The git source of a service's `build:` (short or long form), or None.

    Docker treats a context as git when it starts with `git://` or `git@`, or is
    an http(s) URL whose path ends in `.git`. A fragment is `#ref` or `#ref:subdir`.
    """
    context = build.get("context") if isinstance(build, dict) else build
    if not isinstance(context, str):
        return None
    url, _, fragment = context.partition("#")
    is_http_git = url.startswith(("https://", "http://")) and url.rstrip("/").endswith(".git")
    if not (is_http_git or url.startswith(("git://", "git@"))):
        return None
    ref = fragment.split(":", 1)[0] or None
    return GitSource(url=url, ref=ref)


def _parse_refs(body: bytes) -> dict[str, str]:
    """Ref name -> commit from a pkt-line ref advertisement."""
    refs: dict[str, str] = {}
    position = 0
    while position + 4 <= len(body):
        try:
            length = int(body[position : position + 4], 16)
        except ValueError as exc:
            raise GitError("unexpected answer from the git server") from exc
        if length == 0:  # flush packet
            position += 4
            continue
        line = body[position + 4 : position + length].decode("utf-8", "replace").rstrip("\n")
        position += length
        if line.startswith("#"):  # "# service=git-upload-pack"
            continue
        # The first ref carries the capabilities after a NUL.
        sha, _, name = line.split("\0", 1)[0].partition(" ")
        if _SHA.match(sha) and name:
            refs[name] = sha
    return refs


def list_refs(url: str, auth: tuple[str, str] | None = None) -> dict[str, str]:
    """Ref name -> commit of a repo. `auth` defaults to the stored login for its host."""
    if not url.startswith(("https://", "http://")):
        raise GitError("only http(s) git URLs are checked")
    if auth is None:
        auth = git_auth_service.credentials(url)
    host = git_auth_service.normalize(url)
    try:
        response = httpx.get(
            f"{url.rstrip('/')}/info/refs",
            params={"service": "git-upload-pack"},
            timeout=TIMEOUT,
            follow_redirects=True,
            auth=auth,
        )
    except httpx.HTTPError as exc:
        raise GitError(f"could not reach {url}: {exc}") from exc
    if response.status_code in (401, 403):
        if auth is None:
            raise GitError(f"the repository needs a login: add one for {host} in Settings")
        raise GitError(f"{host} refused the login (HTTP {response.status_code})")
    if response.status_code != 200:
        raise GitError(f"{url} answered HTTP {response.status_code}")
    return _parse_refs(response.content)


def remote_commit(source: GitSource) -> str:
    """Commit the source's ref points to now."""
    if source.ref and _SHA.match(source.ref):
        return source.ref  # pinned to a commit: never changes
    refs = list_refs(source.url)
    ref = source.ref or "HEAD"
    # A tag's peeled entry (^{}) is the commit; the plain one may be a tag object.
    for name in (ref, f"refs/heads/{ref}", f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}"):
        if name in refs:
            return refs[name]
    raise GitError(f"ref {ref} not found in {source.url}")
