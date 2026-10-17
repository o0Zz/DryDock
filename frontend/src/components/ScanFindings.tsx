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
        : detail.findings.filter((f) => f.severity === severity),
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
            {findings.map((f, i) => (
              <tr key={`${f.vulnerability_id}-${f.package_name}-${i}`}>
                <td>
                  <span className={`badge ${severityClass(f.severity)}`}>
                    {f.severity.toLowerCase()}
                  </span>
                </td>
                <td>
                  {f.primary_url ? (
                    <a
                      className="icon-link"
                      href={f.primary_url}
                      target="_blank"
                      rel="noreferrer"
                      title={f.title ?? undefined}
                    >
                      {f.vulnerability_id} <ExternalLink size={13} />
                    </a>
                  ) : (
                    <span title={f.title ?? undefined}>{f.vulnerability_id}</span>
                  )}
                  {f.title && <div className="muted">{f.title}</div>}
                </td>
                <td>
                  {f.package_name}
                  {f.target && <div className="muted">{f.target}</div>}
                </td>
                <td className="muted">{f.installed_version ?? "—"}</td>
                <td>
                  {f.fixed_version ? (
                    <span className="badge running">{f.fixed_version}</span>
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
