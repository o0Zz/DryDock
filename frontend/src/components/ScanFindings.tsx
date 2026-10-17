import { ExternalLink } from "lucide-react";
import { useMemo, useState } from "react";
import type { ScanDetail } from "../types";

const SEVERITY_ORDER = ["CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"];

function severityClass(severity: string): string {
  if (severity === "CRITICAL") return "exited";
  if (severity === "HIGH") return "paused";
  return "";
}

/** Severity filter + findings table for one Trivy scan. */
export default function ScanFindings({ detail }: { detail: ScanDetail }) {
  const [severity, setSeverity] = useState<string>("ALL");

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
            {level.toLowerCase()}
          </button>
        ))}
      </div>
      {detail.truncated && (
        <div className="muted">
          Showing the most severe findings only — the full list was capped.
        </div>
      )}
      {findings.length === 0 ? (
        <div className="empty">No vulnerabilities at this level.</div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <th>Severity</th>
              <th>CVE</th>
              <th>Package</th>
              <th>Installed</th>
              <th>Fixed in</th>
            </tr>
          </thead>
          <tbody>
            {findings.map((finding, index) => (
              <tr key={`${finding.vulnerability_id}-${finding.package_name}-${index}`}>
                <td>
                  <span className={`badge ${severityClass(finding.severity)}`}>
                    {finding.severity.toLowerCase()}
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
                    <span className="muted">no fix</span>
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
