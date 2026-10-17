import {
  ArrowDownCircle,
  ArrowUpCircle,
  ChevronLeft,
  Circle,
  Download,
  Play,
  RotateCw,
  Save,
  ScrollText,
  Square,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useConfirm, type ConfirmOptions } from "../components/ConfirmDialog";
import ImageName from "../components/ImageName";
import LogPanel from "../components/LogPanel";
import { formatPorts } from "../format";
import { isActive, useJobs } from "../hooks/useJobs";
import { imageRepo, retagImage } from "../imageRef";
import type { Project, ProjectAction, UpdateSummary } from "../types";

// CodeMirror is by far the heaviest dependency in the bundle and is only
// needed on this page, so it loads on demand.
const YamlEditor = lazy(() => import("../components/YamlEditor"));

const ACTIONS: ProjectAction[] = ["up", "down", "pull", "restart", "stop"];
const ACTION_ICONS: Record<ProjectAction, LucideIcon> = {
  up: Play,
  down: ArrowDownCircle,
  pull: Download,
  restart: RotateCw,
  stop: Square,
};

// `down` removes containers and networks, so it gets a confirmation step.
const ACTION_CONFIRMATIONS: Partial<Record<ProjectAction, ConfirmOptions>> = {
  down: {
    title: "Bring this stack down?",
    message: "Its containers and networks will be removed. Named volumes are kept.",
    confirmLabel: "Down",
    tone: "danger",
  },
};

// Must match the job label built by the backend route (`Up web`, `Pull web`).
function actionLabel(action: ProjectAction, projectName: string): string {
  return `${action[0].toUpperCase()}${action.slice(1)} ${projectName}`;
}

export default function ProjectDetail() {
  const confirm = useConfirm();
  const { id = "" } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [compose, setCompose] = useState<string>("");
  const [originalCompose, setOriginalCompose] = useState<string>("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  // `?retag=<image>` arrives from a container's update shortcut: offer the
  // newer tags for that image as a one-click edit of the compose file.
  const [searchParams, setSearchParams] = useSearchParams();
  const retag = searchParams.get("retag");
  const [retagUpdate, setRetagUpdate] = useState<UpdateSummary | null>(null);
  const [retagApplied, setRetagApplied] = useState<string | null>(null);
  const [retagNote, setRetagNote] = useState<string | null>(null);

  const reloadProject = useCallback(async (): Promise<void> => {
    setProject(await api.getProject(id));
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getProject(id), api.getCompose(id)])
      .then(([loadedProject, composeFile]) => {
        if (cancelled) return;
        setProject(loadedProject);
        setCompose(composeFile.content);
        setOriginalCompose(composeFile.content);
      })
      .catch((error: Error) => !cancelled && setLoadError(error.message));
    return () => {
      cancelled = true;
    };
  }, [id]);

  useEffect(() => {
    if (!retag) return;
    api
      .listUpdates()
      .then((updateList) =>
        setRetagUpdate(updateList.find((summary) => summary.image === retag) ?? null),
      )
      .catch(() => undefined);
  }, [retag]);

  const save = useCallback(async (): Promise<boolean> => {
    setSaving(true);
    setSaveError(null);
    try {
      const saved = await api.putCompose(id, compose);
      setOriginalCompose(compose);
      setSavedAt(`Saved. Backup: ${saved.backup_path}`);
      return true;
    } catch (error) {
      setSaveError((error as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  }, [id, compose]);

  // Compose actions run as background jobs. Container state almost always
  // changes, so the project reloads when one ends.
  const { jobs, start } = useJobs(() => reloadProject().catch(() => undefined), setActionError);

  const runAction = useCallback(
    async (action: ProjectAction): Promise<void> => {
      const question = ACTION_CONFIRMATIONS[action];
      if (question && !(await confirm(question))) return;
      await start(() => api.runAction(id, action));
    },
    [id, start],
  );

  const applyTag = (tag: string): void => {
    if (!retag) return;
    const result = retagImage(compose, retag, tag);
    if (result.count === 0) {
      setRetagNote(`Could not find "image: ${retag}" in this file. Change the tag by hand below.`);
      return;
    }
    setRetagNote(null);
    setCompose(result.content);
    setRetagApplied(tag);
  };

  const dismissRetag = (): void => {
    searchParams.delete("retag");
    setSearchParams(searchParams, { replace: true });
    setRetagApplied(null);
    setRetagNote(null);
  };

  const saveAndDeploy = async (): Promise<void> => {
    if (await save()) {
      await runAction("up");
      dismissRetag();
    }
  };

  if (loadError) return <div className="error">Failed to load: {loadError}</div>;
  if (!project) return <div>Loading…</div>;

  const dirty = compose !== originalCompose;
  const running = project.containers.filter((container) => container.state === "running").length;
  // useJobs also re-attaches to unrelated jobs (scans); keep this stack's own.
  const actionJobs = jobs.filter(
    (job) =>
      job.kind === "project_action" &&
      ACTIONS.some((action) => job.label === actionLabel(action, project.name)),
  );
  const lastJob = actionJobs[actionJobs.length - 1];
  const busyAction = ACTIONS.find((action) =>
    actionJobs.some((job) => isActive(job) && job.label === actionLabel(action, project.name)),
  );

  return (
    <div>
      <div className="crumb">
        <Link to="/projects">
          <ChevronLeft size={15} /> Projects
        </Link>
      </div>
      <div className="row-between">
        <h1>{project.name}</h1>
        <button type="button" className="secondary" onClick={() => setShowLogs(true)}>
          <ScrollText size={15} /> Stack logs
        </button>
      </div>
      <div className="muted">
        <code>{project.relative_path}</code>
      </div>

      <section className="section">
        <h2>Actions</h2>
        <div className="button-row">
          {ACTIONS.map((action) => {
            const Icon = ACTION_ICONS[action];
            return (
              <button
                key={action}
                type="button"
                disabled={busyAction !== undefined}
                onClick={() => runAction(action)}
              >
                <Icon size={15} /> {busyAction === action ? `${action}…` : action}
              </button>
            );
          })}
        </div>
        {actionError && <div className="error">{actionError}</div>}
        {lastJob && (
          <div
            className={
              isActive(lastJob) ? "output" : lastJob.status === "success" ? "output ok" : "output fail"
            }
          >
            <div className="output-header">
              <strong>{lastJob.label}</strong>
              <span>{isActive(lastJob) ? `${lastJob.status}…` : lastJob.status}</span>
            </div>
            {lastJob.output && <pre>{lastJob.output}</pre>}
            {lastJob.error && !lastJob.output && <pre className="stderr">{lastJob.error}</pre>}
          </div>
        )}
      </section>

      <section className="section">
        <h2>
          Containers{" "}
          <span className="muted">
            {running} of {project.containers.length} running
          </span>
        </h2>
        {project.containers.length === 0 ? (
          <div className="empty">
            No containers for this stack. Deploy it with <strong>up</strong>.
          </div>
        ) : (
          <table className="projects-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Service</th>
                <th>Image</th>
                <th>Status</th>
                <th>Ports</th>
              </tr>
            </thead>
            <tbody>
              {project.containers.map((container) => (
                <tr key={container.id}>
                  <td>{container.name}</td>
                  <td>{container.compose_service ?? "—"}</td>
                  <td>
                    <ImageName image={container.image} version={container.image_version} />
                  </td>
                  <td>
                    <span className={`badge ${container.state}`}>
                      <Circle size={8} fill="currentColor" /> {container.state}
                    </span>
                  </td>
                  <td>
                    {formatPorts(container.ports)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="section">
        <h2>Compose file</h2>
        {retag && (
          <RetagPanel
            image={retag}
            update={retagUpdate}
            applied={retagApplied}
            note={retagNote}
            busy={saving || busyAction !== undefined}
            onApply={applyTag}
            onDeploy={saveAndDeploy}
            onDismiss={dismissRetag}
          />
        )}
        <Suspense fallback={<div className="empty">Loading editor…</div>}>
          <YamlEditor value={compose} onChange={setCompose} />
        </Suspense>
        <div className="button-row">
          <button type="button" onClick={save} disabled={!dirty || saving}>
            <Save size={15} /> {saving ? "Saving…" : "Save"}
          </button>
          <button
            type="button"
            className="secondary"
            onClick={() => setCompose(originalCompose)}
            disabled={!dirty || saving}
          >
            <Undo2 size={15} /> Revert
          </button>
          {savedAt && !dirty && <span className="muted">{savedAt}</span>}
        </div>
        {saveError && <div className="error">{saveError}</div>}
      </section>

      {showLogs && (
        <LogPanel
          title={`${project.name} (stack)`}
          url={`/api/logs/project/${project.id}?tail=200`}
          onClose={() => setShowLogs(false)}
        />
      )}
    </div>
  );
}

function RetagPanel({
  image,
  update,
  applied,
  note,
  busy,
  onApply,
  onDeploy,
  onDismiss,
}: {
  image: string;
  update: UpdateSummary | null;
  applied: string | null;
  note: string | null;
  busy: boolean;
  onApply: (tag: string) => void;
  onDeploy: () => void;
  onDismiss: () => void;
}) {
  // Same-major first: it is the safer upgrade; a new major may need config changes.
  const choices: [string, string][] = [];
  if (update?.newest_same_major_tag) choices.push([update.newest_same_major_tag, "same major"]);
  if (update?.newest_tag && update.newest_tag !== update.newest_same_major_tag) {
    choices.push([update.newest_tag, "newest"]);
  }

  return (
    <div className="output" style={{ padding: "0.75rem" }}>
      {applied ? (
        <div className="button-row">
          <span>
            Image changed to <code>{imageRepo(image)}:{applied}</code> (not saved yet). Review it
            below, then:
          </span>
          <button type="button" disabled={busy} onClick={onDeploy}>
            <Play size={15} /> Save &amp; deploy
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={onDismiss}>
            Close
          </button>
        </div>
      ) : (
        <div className="button-row">
          <span>
            <ArrowUpCircle size={14} /> Update <code>{image}</code>:
          </span>
          {choices.length === 0 ? (
            <span className="muted">no newer tag recorded. Run an update check first.</span>
          ) : (
            choices.map(([tag, label]) => (
              <button key={tag} type="button" className="small" onClick={() => onApply(tag)}>
                Use {tag} <span className="muted">({label})</span>
              </button>
            ))
          )}
          <button type="button" className="secondary small" onClick={onDismiss}>
            Cancel
          </button>
        </div>
      )}
      {note && <div className="error">{note}</div>}
    </div>
  );
}
