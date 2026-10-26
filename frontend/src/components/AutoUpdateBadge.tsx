import { RefreshCcw } from "lucide-react";
import { useT } from "../i18n";
import type { Container } from "../types";

/** Shown on a container labelled `drydock.update=auto`; nothing otherwise. */
export default function AutoUpdateBadge({ container }: { container: Container }) {
  const t = useT();
  if (!container.auto_update) return null;
  return (
    <span
      className="badge"
      title={t(
        "Labelled drydock.update=auto: the scheduled auto-update pulls and recreates it when its tag is rebuilt or its git ref moves.",
      )}
    >
      <RefreshCcw size={12} /> {t("auto-update")}
    </span>
  );
}
