from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.models.job import Job, JobKind
from app.schemas.fail2ban import (
    Fail2banConfig,
    Fail2banConfigRead,
    Fail2banTestRequest,
    Fail2banTestResult,
)
from app.schemas.host import Fail2banReport, HostUpdates
from app.schemas.job import JobRead
from app.services import (
    fail2ban_config_service,
    fail2ban_service,
    host_updates_service,
    job_service,
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
