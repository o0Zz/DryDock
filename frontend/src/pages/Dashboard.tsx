import { Boxes, Layers } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api";
import type { Project } from "../types";

export default function Dashboard() {
  const [projects, setProjects] = useState<Project[] | null>(null);

  useEffect(() => {
    api.listProjects().then(setProjects).catch(() => setProjects([]));
  }, []);

  const projectCount = projects?.length ?? 0;
  const serviceCount = projects?.reduce((sum, p) => sum + p.services.length, 0) ?? 0;

  return (
    <div>
      <h1>Dashboard</h1>
      <div className="stat-grid">
        <div className="stat">
          <div className="stat-icon"><Boxes size={22} /></div>
          <div>
            <div className="stat-value">{projectCount}</div>
            <div className="stat-label">Compose projects</div>
          </div>
        </div>
        <div className="stat">
          <div className="stat-icon"><Layers size={22} /></div>
          <div>
            <div className="stat-value">{serviceCount}</div>
            <div className="stat-label">Services defined</div>
          </div>
        </div>
      </div>
    </div>
  );
}
