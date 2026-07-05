import { FolderGit2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import type { Project } from "../types";

export default function Projects() {
  const [projects, setProjects] = useState<Project[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .listProjects()
      .then(setProjects)
      .catch((e: Error) => setError(e.message));
  }, []);

  if (error) return <div className="error">Failed to load projects: {error}</div>;
  if (!projects) return <div>Loading…</div>;
  if (projects.length === 0) {
    return <div className="empty">No Compose projects found in the mounted repo.</div>;
  }

  return (
    <div>
      <h1>Projects</h1>
      <table className="projects-table">
        <thead>
          <tr>
            <th>Name</th>
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
              <td>{p.services.map((s) => s.name).join(", ") || "—"}</td>
              <td><code>{p.relative_path}</code></td>
              <td>{new Date(p.modified_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
