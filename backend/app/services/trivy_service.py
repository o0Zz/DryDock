from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# How long a single image scan may run before we give up (DB download + scan).
SCAN_TIMEOUT = 600

# Cap on findings persisted per scan. A busy base image can report thousands of
# CVEs; keeping every one would bloat the SQLite file on a Pi for little gain.
# Findings are sorted worst-first before the cap is applied.
MAX_FINDINGS = 500

# Worst first. Lowercased, these are also the count columns on Scan.
SEVERITIES = ("CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN")


class TrivyError(Exception):
    """Raised when trivy cannot be run or the scan fails."""


@dataclass(frozen=True)
class Finding:
    vulnerability_id: str
    severity: str
    package_name: str
    installed_version: str | None = None
    fixed_version: str | None = None
    title: str | None = None
    primary_url: str | None = None
    target: str | None = None


@dataclass
class ScanResult:
    counts: dict[str, int]
    findings: list[Finding] = field(default_factory=list)


def _parse(payload: dict) -> ScanResult:
    counts = {severity.lower(): 0 for severity in SEVERITIES}
    counts["fixable"] = 0
    findings: list[Finding] = []

    for result in payload.get("Results") or []:
        target = result.get("Target")
        for vuln in result.get("Vulnerabilities") or []:
            severity = (vuln.get("Severity") or "").upper()
            if severity not in SEVERITIES:
                continue
            counts[severity.lower()] += 1
            fixed = vuln.get("FixedVersion") or None
            if fixed:
                counts["fixable"] += 1
            findings.append(
                Finding(
                    vulnerability_id=vuln.get("VulnerabilityID") or "UNKNOWN",
                    severity=severity,
                    package_name=vuln.get("PkgName") or "",
                    installed_version=vuln.get("InstalledVersion") or None,
                    fixed_version=fixed,
                    title=vuln.get("Title") or None,
                    primary_url=vuln.get("PrimaryURL") or None,
                    target=target,
                )
            )

    # Worst first, then fixable ones ahead of unfixable, then stable by CVE id.
    findings.sort(
        key=lambda f: (
            SEVERITIES.index(f.severity),
            0 if f.fixed_version else 1,
            f.vulnerability_id,
        )
    )
    return ScanResult(counts=counts, findings=findings[:MAX_FINDINGS])


def scan_image(image: str) -> ScanResult:
    """Scan an image with trivy and return severity counts plus findings.

    Raises TrivyError if trivy cannot run or reports a failure.
    """
    cmd = [
        "trivy",
        "image",
        "--quiet",
        "--scanners",
        "vuln",
        "--format",
        "json",
        "--timeout",
        f"{SCAN_TIMEOUT}s",
        image,
    ]
    logger.info("Scanning image %s with trivy", image)
    try:
        proc = subprocess.run(  # noqa: S603 - args list, no shell
            cmd,
            capture_output=True,
            text=True,
            timeout=SCAN_TIMEOUT + 30,
        )
    except FileNotFoundError as exc:
        raise TrivyError("`trivy` CLI not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise TrivyError(f"trivy scan of {image} timed out") from exc

    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or "unknown error"
        raise TrivyError(f"trivy exited {proc.returncode}: {detail[:500]}")

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise TrivyError("could not parse trivy JSON output") from exc

    return _parse(payload)
