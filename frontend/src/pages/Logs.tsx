import { useState } from "react";
import LogPanel from "../components/LogPanel";
import { useT } from "../i18n";

/** DryDock's own backend logs: scans, jobs, scheduler, errors. */
export default function Logs() {
  const t = useT();
  const [filter, setFilter] = useState("");

  return (
    <div>
      <div className="row-between">
        <h1>{t("Logs")}</h1>
        <input
          type="search"
          placeholder={t("Filter (e.g. WARNING, trivy)")}
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      </div>
      <LogPanel
        title={t("DryDock backend")}
        url="/api/logs/app?tail=500"
        filter={filter}
        inline
      />
    </div>
  );
}
