import { Shield, ShieldAlert, ShieldCheck } from "lucide-react";
import { formatDate } from "../format";
import { useT } from "../i18n";
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
  const t = useT();
  if (pending) return <span className="muted">{t("scanning…")}</span>;

  if (!scan) {
    return (
      <button
        type="button"
        className="linklike"
        title={t("Not scanned yet — click to run a Trivy scan")}
        onClick={onScan}
      >
        <Shield size={14} /> {t("scan")}
      </button>
    );
  }

  const scannedAt = formatDate(scan.scanned_at);

  if (scan.error) {
    return (
      <button
        type="button"
        className="linklike danger"
        title={t("Scan failed: {error}\nClick to retry", { error: scan.error })}
        onClick={onScan}
      >
        <ShieldAlert size={14} /> {t("failed")}
      </button>
    );
  }

  const total = scan.critical + scan.high + scan.medium + scan.low + scan.unknown;
  const severity = scan.critical > 0 ? "exited" : scan.high > 0 ? "paused" : "running";
  const Icon = total === 0 ? ShieldCheck : ShieldAlert;
  const label = total === 0 ? t("clean") : `${scan.critical}C · ${scan.high}H`;

  const tooltip =
    `${t("Last scanned: {date}", { date: scannedAt })}\n` +
    t("Critical {critical} · High {high} · Medium {medium} · Low {low}", {
      critical: scan.critical,
      high: scan.high,
      medium: scan.medium,
      low: scan.low,
    }) +
    (scan.unknown ? ` · ${t("Unknown {count}", { count: scan.unknown })}` : "") +
    (scan.fixable ? `\n${t("{count} with a fix available", { count: scan.fixable })}` : "") +
    `\n${onOpen ? t("Click for details") : t("Click to rescan")}`;

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
