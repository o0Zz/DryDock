"""SQLAlchemy models. Importing this package registers every table on ``Base``."""

from app.models.api_token import ApiToken
from app.models.host_update import HostUpdateCheck
from app.models.job import Job, JobKind, JobStatus
from app.models.scan import Scan, ScanFinding
from app.models.setting import Setting
from app.models.update import UpdateCheck
from app.models.user import User

__all__ = [
    "ApiToken",
    "HostUpdateCheck",
    "Job",
    "JobKind",
    "JobStatus",
    "Scan",
    "ScanFinding",
    "Setting",
    "UpdateCheck",
    "User",
]
