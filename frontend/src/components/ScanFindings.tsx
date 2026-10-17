import { ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import { msg, useT } from "../i18n";
import type { ScanDetail } from "../types";

const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"];

// Trivy's severities stay the filter values; only the button and badge text is translated.
const SEVERITY_LABELS: Record<string, string> = {
  ALL: msg("all"),
  CRITICAL: msg("critical"),
  HIGH: msg("high"),
  MEDIUM: msg("medium"),
  LOW: msg("low"),
  UNKNOWN: msg("unknown"),
};

function severityLabel(severity: string): string {
  return SEVERITY_LABELS[severity] ?? severity.toLowerCase();
}

function severityClass(severity: string): string {
  if (severity === "CRITICAL") return "exited";
  if (severity === "HIGH") return "paused";
  return "";
}

/** Severity filter + findings table for one Trivy scan. */
export default function ScanFindings({ detail }: { detail: ScanDetail }) {
  const [severity, setSeverity] = useState<string>("ALL");
  const t = useT();

  const findings = useMemo(
    () =>
      severity === "ALL"
        ? detail.findings
        : detail.findings.filter((finding) => finding.severity === severity),
    [detail.findings, severity],
  );

  if (detail.error) return <div className="error">{detail.error}</div>;

  return (
    <>
      <div className="button-row">
        {["ALL", ...SEVERITY_ORDER].map((level) => (
          <button
            key={level}
            type="button"
            className={severity === level ? "small" : "secondary small"}
            onClick={() => setSeverity(level)}
          >
            {t(severityLabel(level))}
          </button>
        ))}
      </div>
      {detail.truncated && (
        <div className="muted">
          {t("Showing the most severe findings only — the full list was capped.")}
        </div>
      )}
      {findings.length === 0 ? (
        <div className="empty">{t("No vulnerabilities at this level.")}</div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <th>{t("Severity")}</th>
              <th>CVE</th>
              <th>{t("Package")}</th>
              <th>{t("Installed")}</th>
              <th>{t("Fixed in")}</th>
            </tr>
          </thead>
          <tbody>
            {findings.map((finding, index) => (
              <tr key={`${finding.vulnerability_id}-${finding.package_name}-${index}`}>
                <td>
                  <span className={`badge ${severityClass(finding.severity)}`}>
                    {t(severityLabel(finding.severity))}
                  </span>
                </td>
                <td>
                  {finding.primary_url ? (
                    <a
                      className="icon-link"
                      href={finding.primary_url}
                      target="_blank"
                      rel="noreferrer"
                      title={finding.title ?? undefined}
                    >
                      {finding.vulnerability_id} <ExternalLink size={13} />
                    </a>
                  ) : (
                    <span title={finding.title ?? undefined}>{finding.vulnerability_id}</span>
                  )}
                  {finding.title && <div className="muted">{finding.title}</div>}
                </td>
                <td>
                  {finding.package_name}
                  {finding.target && <div className="muted">{finding.target}</div>}
                </td>
                <td className="muted">{finding.installed_version ?? "—"}</td>
                <td>
                  {finding.fixed_version ? (
                    <span className="badge running">{finding.fixed_version}</span>
                  ) : (
                    <span className="muted">{t("no fix")}</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  );
}
