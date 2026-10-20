import { FolderGit2, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useConfirm } from "../components/ConfirmDialog";
import SortHeader from "../components/SortHeader";
import { formatDate } from "../format";
import { useSort } from "../hooks/useSort";
import { useT } from "../i18n";
import { askDelete, waitForJob } from "../stackActions";
import type { Project } from "../types";

// Down, then stopped, partial and up, so stacks that need a look come first.
function stackRank(project: Project): number {
  const total = project.containers.length;
  if (total === 0) return 0;
  const running = project.containers.filter((container) => container.state === "running").length;
  return running === 0 ? 1 : running < total ? 2 : 3;
}

function StackStatus({ project }: { project: Project }) {
  const t = useT();
  const total = project.containers.length;
  if (total === 0) return <span className="badge">{t("down")}</span>;
  const running = project.containers.filter((container) => container.state === "running").length;
  if (running === total) return <span className="badge running">{t("up ({running})", { running })}</span>;
  if (running === 0) return <span className="badge exited">{t("stopped ({total})", { total })}</span>;
  return (
    <span className="badge paused">{t("partial ({running}/{total})", { running, total })}</span>
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
  const t = useT();
  const sorting = useSort(projects, {
    storageKey: "drydock.sort.projects",
    columns: {
      name: (project) => project.name,
      status: stackRank,
      services: (project) => project.services.length,
      path: (project) => project.relative_path,
      modified: (project) => Date.parse(project.modified_at),
    },
    initial: { column: "name", descending: false },
    descendingFirst: ["services", "modified"],
  });

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

  if (error) return <div className="error">{t("Failed to load projects: {error}", { error })}</div>;
  if (!projects) return <div>{t("Loading…")}</div>;

  return (
    <div>
      <div className="row-between">
        <h1>{t("Projects")}</h1>
        <button type="button" onClick={() => navigate("/projects/new")}>
          <Plus size={15} /> {t("New stack")}
        </button>
      </div>
      {actionError && <div className="error">{actionError}</div>}
      {notice && (
        <div className="output ok padded">
          {notice}
        </div>
      )}
      {projects.length === 0 ? (
        <div className="empty">{t("No Compose projects found in the mounted repo.")}</div>
      ) : (
        <table className="projects-table">
          <thead>
            <tr>
              <SortHeader sorting={sorting} column="name">
                {t("Name")}
              </SortHeader>
              <SortHeader sorting={sorting} column="status">
                {t("Status")}
              </SortHeader>
              <SortHeader sorting={sorting} column="services">
                {t("Services")}
              </SortHeader>
              <SortHeader sorting={sorting} column="path">
                {t("Path")}
              </SortHeader>
              <SortHeader sorting={sorting} column="modified">
                {t("Modified")}
              </SortHeader>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {sorting.rows.map((project) => (
              <tr key={project.id}>
                <td>
                  <Link className="icon-link row-name" to={`/projects/${project.id}`}>
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
                    title={t("Delete this stack")}
                    aria-label={t("delete")}
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
