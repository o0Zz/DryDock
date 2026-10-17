from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import require_admin
from app.models.job import Job, JobKind
from app.schemas.host import Fail2banReport, HostUpdates
from app.schemas.job import JobRead
from app.services import fail2ban_service, host_updates_service, job_service, tasks

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
