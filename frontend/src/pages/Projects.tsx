import { FolderGit2, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useConfirm } from "../components/ConfirmDialog";
import { formatDate } from "../format";
import { askDelete, waitForJob } from "../stackActions";
import type { Project } from "../types";

function StackStatus({ project }: { project: Project }) {
  const total = project.containers.length;
  if (total === 0) return <span className="badge">down</span>;
  const running = project.containers.filter((container) => container.state === "running").length;
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
  const [actionError, setActionError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  // The stack being deleted, while its job runs.
  const [deleting, setDeleting] = useState<string | null>(null);
  const navigate = useNavigate();
  const confirm = useConfirm();

  const load = useCallback((): void => {
    api
      .listProjects()
      .then(setProjects)
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  async function remove(project: Project): Promise<void> {
    const choice = await askDelete(confirm, project);
    if (!choice) return;
    setActionError(null);
    setNotice(null);
    setDeleting(project.id);
    try {
      const job = await waitForJob(await api.deleteProject(project.id, choice.removeVolumes));
      setNotice(job.message);
    } catch (deleteError) {
      setActionError((deleteError as Error).message);
    } finally {
      setDeleting(null);
      load();
    }
  }

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
      {actionError && <div className="error">{actionError}</div>}
      {notice && (
        <div className="output ok" style={{ padding: "0.75rem" }}>
          {notice}
        </div>
      )}
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
              <th></th>
            </tr>
          </thead>
          <tbody>
            {projects.map((project) => (
              <tr key={project.id}>
                <td>
                  <Link className="icon-link" to={`/projects/${project.id}`}>
                    <FolderGit2 size={15} /> {project.name}
                  </Link>
                </td>
                <td>
                  <StackStatus project={project} />
                </td>
                <td>{project.services.map((service) => service.name).join(", ") || "—"}</td>
                <td>
                  <code>{project.relative_path}</code>
                </td>
                <td>{formatDate(project.modified_at)}</td>
                <td>
                  <button
                    type="button"
                    className="secondary small icon-only"
                    title="Delete this stack"
                    aria-label="delete"
                    disabled={deleting !== null}
                    onClick={() => remove(project)}
                  >
                    <Trash2 size={14} />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
