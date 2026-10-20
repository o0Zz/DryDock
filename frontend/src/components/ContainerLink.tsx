import { Circle } from "lucide-react";
import { Link } from "react-router-dom";
import { useT } from "../i18n";

/** Link to a container's page, with a dot for running or stopped. */
export default function ContainerLink({
  id,
  name,
  running,
}: {
  id: string;
  name: string;
  running: boolean;
}) {
  const t = useT();
  return (
    <Link
      className="icon-link"
      to={`/containers/${id}`}
      title={running ? t("running") : t("stopped")}
    >
      <Circle size={8} fill="currentColor" className={running ? "dot-running" : "dot-stopped"} />{" "}
      {name}
    </Link>
  );
}
