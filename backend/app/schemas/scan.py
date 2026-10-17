from pydantic import BaseModel, ConfigDict

from app.schemas.common import UtcDatetime


class ScanRequest(BaseModel):
    image: str


class ScanSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    image: str
    scanned_at: UtcDatetime
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    unknown: int = 0
    fixable: int = 0
    # Populated when the scan itself failed (e.g. trivy error); counts are 0.
    error: str | None = None


class ScanFindingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vulnerability_id: str
    severity: str
    package_name: str
    installed_version: str | None = None
    fixed_version: str | None = None
    title: str | None = None
    primary_url: str | None = None
    target: str | None = None


class ScanDetail(ScanSummary):
    findings: list[ScanFindingRead] = []
    # True when the finding list was capped (see trivy_service.MAX_FINDINGS).
    truncated: bool = False
