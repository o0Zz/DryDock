import { useState } from "react";
import LogPanel from "../components/LogPanel";

/** DryDock's own backend logs: scans, jobs, scheduler, errors. */
export default function Logs() {
  const [filter, setFilter] = useState("");

  return (
    <div>
      <div className="row-between">
        <h1>Logs</h1>
        <input
          type="search"
          placeholder="Filter (e.g. WARNING, trivy)"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      </div>
      <LogPanel title="DryDock backend" url="/api/logs/app?tail=500" filter={filter} inline />
    </div>
  );
}
