import { formatDate, formatDuration, secondsSince } from "../format";
import { useT } from "../i18n";
import type { Container } from "../types";

/** Seconds a running or paused container has been up, or null when it is not up. */
export function uptimeSeconds(container: Container): number | null {
  return isUp(container) ? secondsSince(container.started_at) : null;
}

// A paused container keeps its processes, so it still counts as up.
function isUp(container: Container): boolean {
  return container.state === "running" || container.state === "paused";
}

/** How long a running container has been up, or how long ago a stopped one stopped. */
export default function Uptime({ container }: { container: Container }) {
  const t = useT();
  const title = [
    t("Created {date}", { date: formatDate(container.created_at) }),
    t("Started {date}", { date: formatDate(container.started_at, t("never")) }),
    container.finished_at && t("Stopped {date}", { date: formatDate(container.finished_at) }),
  ]
    .filter(Boolean)
    .join("\n");
  if (isUp(container)) {
    const seconds = secondsSince(container.started_at);
    return <span title={title}>{seconds === null ? "—" : formatDuration(seconds)}</span>;
  }
  const stopped = secondsSince(container.finished_at);
  return (
    <span className="muted" title={title}>
      {stopped === null ? "—" : t("stopped {duration} ago", { duration: formatDuration(stopped) })}
    </span>
  );
}
