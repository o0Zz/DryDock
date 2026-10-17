import { Shield, ShieldAlert, ShieldCheck } from "lucide-react";
import type { ScanSummary } from "../types";

/** Compact CVE summary for one image; clicking it queues a (re)scan. */
export default function ScanBadge({
  scan,
  pending,
  onScan,
  onOpen,
}: {
  scan: ScanSummary | undefined;
  pending: boolean;
  onScan: () => void;
  onOpen?: (scan: ScanSummary) => void;
}) {
  if (pending) return <span className="muted">scanning…</span>;

  if (!scan) {
    return (
      <button
        type="button"
        className="linklike"
        title="Not scanned yet — click to run a Trivy scan"
        onClick={onScan}
      >
        <Shield size={14} /> scan
      </button>
    );
  }

  const when = new Date(scan.scanned_at).toLocaleString();

  if (scan.error) {
    return (
      <button
        type="button"
        className="linklike danger"
        title={`Scan failed: ${scan.error}\nClick to retry`}
        onClick={onScan}
      >
        <ShieldAlert size={14} /> failed
      </button>
    );
  }

  const total = scan.critical + scan.high + scan.medium + scan.low + scan.unknown;
  const severity = scan.critical > 0 ? "exited" : scan.high > 0 ? "paused" : "running";
  const Icon = total === 0 ? ShieldCheck : ShieldAlert;
  const label = total === 0 ? "clean" : `${scan.critical}C · ${scan.high}H`;

  const tooltip =
    `Last scanned: ${when}\n` +
    `Critical ${scan.critical} · High ${scan.high} · ` +
    `Medium ${scan.medium} · Low ${scan.low}` +
    (scan.unknown ? ` · Unknown ${scan.unknown}` : "") +
    (scan.fixable ? `\n${scan.fixable} with a fix available` : "") +
    (onOpen ? "\nClick for details" : "\nClick to rescan");

  return (
    <button
      type="button"
      className={`badge ${severity} scan-badge`}
      title={tooltip}
      onClick={() => (onOpen ? onOpen(scan) : onScan())}
    >
      <Icon size={12} /> {label}
    </button>
  );
}
