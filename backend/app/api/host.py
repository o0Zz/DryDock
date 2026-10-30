from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.models.job import Job, JobKind
from app.schemas.blocklist import IpBlocklistCheck, IpBlocklistConfig, IpBlocklistRead
from app.schemas.fail2ban import (
    Fail2banEdit,
    Fail2banFileChange,
    Fail2banJailConfig,
    Fail2banJails,
    Fail2banNewJail,
    Fail2banPlan,
    Fail2banTestRequest,
    Fail2banTestResult,
)
from app.schemas.host import Fail2banReport, HostUpdates
from app.schemas.job import JobRead
from app.services import (
    blocklist_service,
    fail2ban_config_service,
    fail2ban_service,
    host_updates_service,
    job_service,
    scheduler_service,
    tasks,
)
from app.services import fail2ban_jails as fail2ban_jails_service

router = APIRouter(prefix="/api/host", tags=["host"])


@router.get("/updates", response_model=HostUpdates | None)
def host_updates(db: Session = Depends(get_db)) -> HostUpdates | None:
    """The latest check, or null when the host was never checked."""
    return host_updates_service.latest(db)


@router.post("/updates/check", response_model=JobRead, status_code=status.HTTP_202_ACCEPTED)
def check_host_updates() -> Job:
    return job_service.submit(
        JobKind.HOST_UPDATE_CHECK, "Host update check", tasks.host_update_check_runner()
    )


# The matched log lines show IPs, user names and request paths, like the app log.
@router.get("/fail2ban", response_model=Fail2banReport, dependencies=[Depends(require_admin)])
def fail2ban() -> Fail2banReport:
    return fail2ban_service.report()


# fail2ban's jails, read from the host's files and edited in place. Writing them changes
# the host, so it is admin only. Reading and planning block a few seconds instead of being
# jobs: the user waits for the answer, and they only read the host.
@router.get("/fail2ban/jails", response_model=Fail2banJails, dependencies=[Depends(require_admin)])
def fail2ban_jails() -> Fail2banJails:
    snapshot = fail2ban_config_service.snapshot()
    return Fail2banJails(
        jails=fail2ban_jails_service.read_jails(snapshot),
        templates=list(fail2ban_jails_service.TEMPLATES),
    )


@router.post(
    "/fail2ban/new", response_model=Fail2banJailConfig, dependencies=[Depends(require_admin)]
)
def new_fail2ban_jail(body: Fail2banNewJail) -> Fail2banJailConfig:
    """A new jail's two files from a template, to edit before applying. Nothing is written."""
    return fail2ban_jails_service.new_jail(body)


@router.post("/fail2ban/plan", response_model=Fail2banPlan, dependencies=[Depends(require_admin)])
def plan_fail2ban(body: Fail2banEdit) -> Fail2banPlan:
    """The files an edit would change, before and after, without writing them."""
    snapshot = fail2ban_config_service.snapshot()
    changes = fail2ban_jails_service.plan(snapshot, body)
    return Fail2banPlan(
        files=[
            Fail2banFileChange(path=path, before=snapshot.files.get(path), after=after)
            for path, after in changes.items()
        ]
    )


@router.post(
    "/fail2ban/apply",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
def apply_fail2ban(body: Fail2banEdit) -> Job:
    return job_service.submit(
        JobKind.FAIL2BAN_APPLY, "Apply fail2ban changes", tasks.fail2ban_apply_runner(body)
    )


@router.post(
    "/fail2ban/test", response_model=Fail2banTestResult, dependencies=[Depends(require_admin)]
)
def test_fail2ban_jail(body: Fail2banTestRequest) -> Fail2banTestResult:
    return fail2ban_config_service.test(body)


# Known bad IPs dropped by the host's nftables. It changes the host's firewall, so the
# whole feature is admin only.
@router.get("/blocklist", response_model=IpBlocklistRead, dependencies=[Depends(require_admin)])
def blocklist(db: Session = Depends(get_db)) -> IpBlocklistRead:
    return IpBlocklistRead(
        config=blocklist_service.get_config(db),
        status=blocklist_service.status(),
        host=blocklist_service.host_state(),
    )


@router.put("/blocklist", response_model=IpBlocklistRead, dependencies=[Depends(require_admin)])
def save_blocklist(body: IpBlocklistConfig, db: Session = Depends(get_db)) -> IpBlocklistRead:
    """Store the config and its schedule. Nothing changes on the host until it is applied."""
    blocklist_service.save_config(db, body)
    scheduler_service.reconfigure()
    return IpBlocklistRead(
        config=body, status=blocklist_service.status(), host=blocklist_service.host_state()
    )


@router.post(
    "/blocklist/apply",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
def apply_blocklist() -> Job:
    return job_service.submit(
        JobKind.BLOCKLIST_APPLY, "Apply the IP blocklist", tasks.blocklist_apply_runner()
    )


@router.get(
    "/blocklist/check", response_model=IpBlocklistCheck, dependencies=[Depends(require_admin)]
)
def check_blocklist(ip: str) -> IpBlocklistCheck:
    """Whether the last loaded list blocks `ip`."""
    try:
        return blocklist_service.check(ip.strip())
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"not an IP address: {ip}") from exc
