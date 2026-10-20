from typing import Literal

from pydantic import BaseModel, Field


class GitCredentialRead(BaseModel):
    host: str
    username: str


class GitCredentialCreate(BaseModel):
    # A host (`git.example.com`) or a repo URL. With a repo URL, the login is
    # checked against that repo before it is saved.
    url: str = Field(
        min_length=1, max_length=2048, pattern=r"^(https?://)?[A-Za-z0-9.-]+(:\d+)?(/\S*)?$"
    )
    username: str = Field(min_length=1, max_length=255)
    # Password or access token. Write-only: never returned by the API.
    token: str = Field(min_length=1, max_length=4096)


class RepoChange(BaseModel):
    # `git status --porcelain` code, e.g. " M", "??".
    status: str
    path: str


class RepoGitStatus(BaseModel):
    supported: bool
    reason: str | None = None
    branch: str | None = None
    upstream: str | None = None
    ahead: int = 0
    behind: int = 0
    remote_url: str | None = None
    has_login: bool = False
    changes: list[RepoChange] = []


class RepoCommit(BaseModel):
    message: str = Field(min_length=1, max_length=5000)
    push: bool = True


RepoGitAction = Literal["push", "pull"]
