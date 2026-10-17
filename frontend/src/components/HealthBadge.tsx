import { HeartPulse } from "lucide-react";
import { msg, useT } from "../i18n";

// Reuse the state colours: healthy reads like running, unhealthy like exited.
const HEALTH_CLASS: Record<string, string> = {
  healthy: "running",
  unhealthy: "exited",
  starting: "paused",
};

// Docker's health values as shown; the raw value stays the CSS lookup key.
const HEALTH_LABELS: Record<string, string> = {
  healthy: msg("healthy"),
  unhealthy: msg("unhealthy"),
  starting: msg("starting"),
};

/** Health check result of a container; renders nothing when it has no check. */
export default function HealthBadge({ health }: { health: string | null }) {
  const t = useT();
  if (!health) return null;
  return (
    <span className={`badge ${HEALTH_CLASS[health] ?? ""}`} title={t("Health check")}>
      <HeartPulse size={10} /> {t(HEALTH_LABELS[health] ?? health)}
    </span>
  );
}
