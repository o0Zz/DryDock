import { Circle } from "lucide-react";
import { containerStateLabel } from "../containerActions";
import { useT } from "../i18n";
import type { Container } from "../types";
import HealthBadge from "./HealthBadge";

/** State badge, health and restart count of a container, for a table cell. */
export default function ContainerStatus({
  container,
  title,
}: {
  container: Container;
  title?: string;
}) {
  const t = useT();
  return (
    <>
      <span className={`badge ${container.state}`} title={title}>
        <Circle size={8} fill="currentColor" /> {t(containerStateLabel(container.state))}
      </span>{" "}
      <HealthBadge health={container.health} />
      {container.restart_count > 0 && (
        <div className="muted" title={t("Restarts since the container was created")}>
          {container.restart_count === 1
            ? t("1 restart")
            : t("{count} restarts", { count: container.restart_count })}
        </div>
      )}
    </>
  );
}
