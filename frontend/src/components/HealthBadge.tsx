import { HeartPulse } from "lucide-react";

// Reuse the state colours: healthy reads like running, unhealthy like exited.
const HEALTH_CLASS: Record<string, string> = {
  healthy: "running",
  unhealthy: "exited",
  starting: "paused",
};

/** Health check result of a container; renders nothing when it has no check. */
export default function HealthBadge({ health }: { health: string | null }) {
  if (!health) return null;
  return (
    <span className={`badge ${HEALTH_CLASS[health] ?? ""}`} title="Health check">
      <HeartPulse size={10} /> {health}
    </span>
  );
}
