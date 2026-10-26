from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings as env_settings
from app.core.database import get_db
from app.core.security import require_admin
from app.schemas.setting import SettingsRead, SettingsUpdate
from app.services import scheduler_service, settings_service

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _read(db: Session) -> SettingsRead:
    values = settings_service.get_all(db)
    next_runs = scheduler_service.next_run_times()
    return SettingsRead(
        **values,
        next_scan_run=next_runs.get(scheduler_service.SCAN_JOB_ID),
        next_update_run=next_runs.get(scheduler_service.UPDATE_JOB_ID),
        next_auto_update_run=next_runs.get(scheduler_service.AUTO_UPDATE_JOB_ID),
        repo_path=str(env_settings.repo_path),
        data_path=str(env_settings.data_path),
    )


@router.get("", response_model=SettingsRead)
def read_settings(db: Session = Depends(get_db)) -> SettingsRead:
    return _read(db)


@router.put("", response_model=SettingsRead, dependencies=[Depends(require_admin)])
def write_settings(body: SettingsUpdate, db: Session = Depends(get_db)) -> SettingsRead:
    payload = body.model_dump(exclude_unset=True, exclude_none=True)
    if payload:
        settings_service.set_many(db, payload)
        # Intervals and on/off switches only take effect once the scheduler
        # re-reads them.
        scheduler_service.reconfigure()
    return _read(db)
