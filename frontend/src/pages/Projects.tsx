import { FolderGit2, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import type { Project } from "../types";

function StackStatus({ project }: { project: Project }) {
  const total = project.containers.length;
  if (total === 0) return <span className="badge">down</span>;
  const running = project.containers.filter((c) => c.state === "running").length;
  if (running === total) return <span className="badge running">up ({running})</span>;
  if (running === 0) return <span className="badge exited">stopped ({total})</span>;
  return (
    <span className="badge paused">
      partial ({running}/{total})
    </span>
  );
}

export default function Projects() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    api
      .listProjects()
      .then(setProjects)
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="error">Failed to load projects: {error}</div>;
  if (!projects) return <div>Loading…</div>;

  return (
    <div>
      <div className="row-between">
        <h1>Projects</h1>
        <button type="button" onClick={() => navigate("/projects/new")}>
          <Plus size={15} /> New stack
        </button>
      </div>
      {projects.length === 0 ? (
        <div className="empty">No Compose projects found in the mounted repo.</div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Status</th>
              <th>Services</th>
              <th>Path</th>
              <th>Modified</th>
            </tr>
          </thead>
          <tbody>
            {projects.map((p) => (
              <tr key={p.id}>
                <td>
                  <Link className="icon-link" to={`/projects/${p.id}`}>
                    <FolderGit2 size={15} /> {p.name}
                  </Link>
                </td>
                <td>
                  <StackStatus project={p} />
                </td>
                <td>{p.services.map((s) => s.name).join(", ") || "—"}</td>
                <td>
                  <code>{p.relative_path}</code>
                </td>
                <td>{new Date(p.modified_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
