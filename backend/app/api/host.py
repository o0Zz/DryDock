from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.models.job import Job, JobKind
from app.schemas.blocklist import IpBlocklistCheck, IpBlocklistConfig, IpBlocklistRead
from app.schemas.fail2ban import (
    Fail2banConfig,
    Fail2banConfigRead,
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


# DryDock's own jails against the proxy's access log. Writing them changes the host,
# so the whole config is admin only.
@router.get(
    "/fail2ban/config", response_model=Fail2banConfigRead, dependencies=[Depends(require_admin)]
)
def fail2ban_config(db: Session = Depends(get_db)) -> Fail2banConfigRead:
    config = fail2ban_config_service.get_config(db)
    return Fail2banConfigRead(config=config, applied=fail2ban_config_service.applied(config))


@router.put(
    "/fail2ban/config", response_model=Fail2banConfigRead, dependencies=[Depends(require_admin)]
)
def save_fail2ban_config(
    body: Fail2banConfig, db: Session = Depends(get_db)
) -> Fail2banConfigRead:
    """Store the config. Nothing changes on the host until it is applied."""
    fail2ban_config_service.save_config(db, body)
    return Fail2banConfigRead(config=body, applied=fail2ban_config_service.applied(body))


@router.post(
    "/fail2ban/apply",
    response_model=JobRead,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_admin)],
)
def apply_fail2ban_config(db: Session = Depends(get_db)) -> Job:
    config = fail2ban_config_service.get_config(db)
    return job_service.submit(
        JobKind.FAIL2BAN_APPLY, "Apply fail2ban jails", tasks.fail2ban_apply_runner(config)
    )


# Blocks a few seconds instead of being a job: the user waits for the answer, and it
# only reads the host.
@router.post(
    "/fail2ban/test", response_model=Fail2banTestResult, dependencies=[Depends(require_admin)]
)
def test_fail2ban_jail(body: Fail2banTestRequest) -> Fail2banTestResult:
    return fail2ban_config_service.test(body.config, body.jail)


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
