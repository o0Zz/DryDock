from dataclasses import asdict
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.security import require_admin
from app.models.job import Job, JobKind
from app.models.user import User
from app.schemas.git import (
    GitCredentialCreate,
    GitCredentialRead,
    GitCredentialUpdate,
    RepoCommit,
    RepoGitAction,
    RepoGitStatus,
)
from app.schemas.job import JobRead
from app.services import git_auth_service, git_service, job_service, repo_git_service, tasks

# Logins reach private repos, and a push publishes the repo folder (`.env` files
# included unless ignored), so only admins use any of this.
router = APIRouter(prefix="/api/git", tags=["git"], dependencies=[Depends(require_admin)])


@router.get("/credentials", response_model=list[GitCredentialRead])
def list_credentials() -> list[GitCredentialRead]:
    return [
        GitCredentialRead(host=host, username=username)
        for host, username in git_auth_service.list_hosts()
    ]


@router.post("/credentials", response_model=GitCredentialRead, status_code=status.HTTP_201_CREATED)
def add_credentials(body: GitCredentialCreate) -> GitCredentialRead:
    """Store a login. Given a repo URL, check it against that repo first."""
    _check_login(body.url, body.username, body.token)
    host = git_auth_service.set_credentials(body.url, body.username, body.token)
    return GitCredentialRead(host=host, username=body.username)


@router.put("/credentials", response_model=GitCredentialRead)
def update_credentials(body: GitCredentialUpdate, host: str = Query()) -> GitCredentialRead:
    """Change a stored login: its host, username or token (empty keeps it)."""
    current = git_auth_service.credentials(host)
    if current is None:
        raise HTTPException(status_code=404, detail=f"No git login for {host}")
    token = body.token or current[1]
    _check_login(body.url, body.username, token)
    if git_auth_service.normalize(body.url) != git_auth_service.normalize(host):
        git_auth_service.remove_credentials(host)
    new_host = git_auth_service.set_credentials(body.url, body.username, token)
    return GitCredentialRead(host=new_host, username=body.username)


def _check_login(url: str, username: str, token: str) -> None:
    """Check a login against a repo, when `url` names one. A bare host cannot be checked."""
    url = url.strip()
    url = url if "://" in url else f"https://{url}"
    if not urlsplit(url).path.strip("/"):
        return
    try:
        git_service.list_refs(url, auth=(username, token))
    except git_service.GitError as exc:
        raise HTTPException(status_code=400, detail=f"Login check failed: {exc}") from exc


@router.delete("/credentials", status_code=status.HTTP_204_NO_CONTENT)
def remove_credentials(host: str = Query()) -> None:
    if not git_auth_service.remove_credentials(host):
        raise HTTPException(status_code=404, detail=f"No git login for {host}")


@router.get("/repo", response_model=RepoGitStatus)
def repo_status() -> RepoGitStatus:
    try:
        return RepoGitStatus.model_validate(asdict(repo_git_service.status()))
    except repo_git_service.RepoGitError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/repo/commit", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def commit(body: RepoCommit, user: User = Depends(require_admin)) -> Job:
    action = "commit_push" if body.push else "commit"
    label = "Commit and push the repo" if body.push else "Commit the repo"
    runner = tasks.repo_git_runner(action, message=body.message, username=user.username)
    return job_service.submit(JobKind.REPO_GIT, label, runner)


@router.post("/repo/{action}", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def push_or_pull(action: RepoGitAction) -> Job:
    label = "Push the repo" if action == "push" else "Pull the repo"
    return job_service.submit(JobKind.REPO_GIT, label, tasks.repo_git_runner(action))
