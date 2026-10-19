import {
  ArrowDownCircle,
  ArrowUpCircle,
  ChevronLeft,
  Circle,
  Copy,
  Download,
  PenLine,
  Play,
  RotateCw,
  Save,
  ScrollText,
  Square,
  Trash2,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { lazy, Suspense, useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useConfirm, type ConfirmOptions } from "../components/ConfirmDialog";
import HealthBadge from "../components/HealthBadge";
import ImageName from "../components/ImageName";
import { JOB_STATUS_TEXT } from "../components/JobList";
import LogPanel from "../components/LogPanel";
import SortHeader from "../components/SortHeader";
import Uptime from "../components/Uptime";
import { containerStateLabel, containerStateRank } from "../containerActions";
import { formatDate, formatPorts, secondsSince } from "../format";
import { isActive, useJobs } from "../hooks/useJobs";
import { useSort } from "../hooks/useSort";
import { msg, useT } from "../i18n";
import { imageRepo, retagImage } from "../imageRef";
import { askDelete, askName, waitForJob } from "../stackActions";
import type { Project, ProjectAction, UpdateSummary } from "../types";

// CodeMirror is by far the heaviest dependency in the bundle and is only
// needed on this page, so it loads on demand.
const YamlEditor = lazy(() => import("../components/YamlEditor"));

const ACTIONS: ProjectAction[] = ["up", "down", "pull", "reload", "stop"];
const ACTION_ICONS: Record<ProjectAction, LucideIcon> = {
  up: Play,
  down: ArrowDownCircle,
  pull: Download,
  reload: RotateCw,
  stop: Square,
};

// Button text when it differs from the action name. Action names are Compose
// commands and stay untranslated in every language.
const ACTION_TEXT: Partial<Record<ProjectAction, string>> = { pull: "pull & build" };

const ACTION_HINTS: Record<ProjectAction, string> = {
  up: msg("Start the stack; recreates services whose config changed"),
  down: msg("Stop and remove the stack's containers and networks"),
  pull: msg(
    "Download newer images and rebuild services with a build: section (applied on up or reload)",
  ),
  reload: msg("Stop the stack, then up: applies your Compose file changes"),
  stop: msg("Stop the containers without removing them"),
};

// `down` removes containers and networks, so it gets a confirmation step.
const ACTION_CONFIRMATIONS: Partial<Record<ProjectAction, ConfirmOptions>> = {
  down: {
    title: msg("Bring this stack down?"),
    message: msg("Its containers and networks will be removed. Named volumes are kept."),
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
  const t = useT();
  const { id = "" } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const sorting = useSort(project?.containers, {
    storageKey: "drydock.sort.stack-containers",
    columns: {
      name: (container) => container.name,
      service: (container) => container.compose_service,
      image: (container) => container.image,
      status: (container) => containerStateRank(container.state),
      uptime: (container) =>
        ["running", "paused"].includes(container.state) ? secondsSince(container.started_at) : null,
    },
    initial: { column: "name", descending: false },
    descendingFirst: ["uptime"],
  });
  const [compose, setCompose] = useState<string>("");
  const [originalCompose, setOriginalCompose] = useState<string>("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [showLogs, setShowLogs] = useState(false);
  // Label of the delete, rename or duplicate job while it runs.
  const [stackBusy, setStackBusy] = useState<string | null>(null);
  const [stackNotice, setStackNotice] = useState<ReactNode>(null);
  const navigate = useNavigate();
  const { user } = useAuth();
  const [fileTab, setFileTab] = useState<"compose" | "env">("compose");
  // The .env editor mounts on first open and then stays, so switching tabs keeps edits.
  const [envOpened, setEnvOpened] = useState(false);
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
      setSavedAt(t("Saved. Backup: {path}", { path: saved.backup_path }));
      // Picks up the new modified time for the "changed since deployed" hint.
      reloadProject().catch(() => undefined);
      return true;
    } catch (error) {
      setSaveError((error as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  }, [id, compose, t, reloadProject]);

  // Compose actions run as background jobs. Container state almost always
  // changes, so the project reloads when one ends.
  const { jobs, start } = useJobs(() => reloadProject().catch(() => undefined), setActionError);

  const runAction = useCallback(
    async (action: ProjectAction): Promise<void> => {
      const question = ACTION_CONFIRMATIONS[action];
      if (question) {
        const accepted = await confirm({
          ...question,
          title: t(question.title),
          message: typeof question.message === "string" ? t(question.message) : question.message,
        });
        if (!accepted) return;
      }
      await start(() => api.runAction(id, action));
    },
    [id, start, confirm, t],
  );

  const applyTag = (tag: string): void => {
    if (!retag) return;
    const result = retagImage(compose, retag, tag);
    if (result.count === 0) {
      setRetagNote(
        t("Could not find \"image: {image}\" in this file. Change the tag by hand below.", {
          image: retag,
        }),
      );
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

  const changeStack = async (label: string, change: () => Promise<void>): Promise<void> => {
    setActionError(null);
    setStackNotice(null);
    setStackBusy(label);
    try {
      await change();
    } catch (changeError) {
      setActionError((changeError as Error).message);
    } finally {
      setStackBusy(null);
    }
  };

  const deleteStack = async (): Promise<void> => {
    if (!project) return;
    const choice = await askDelete(confirm, project);
    if (!choice) return;
    await changeStack(t("Deleting…"), async () => {
      await waitForJob(await api.deleteProject(id, choice.removeVolumes));
      navigate("/projects");
    });
  };

  const renameStack = async (): Promise<void> => {
    if (!project) return;
    const name = await askName(confirm, {
      title: t("Rename stack {name}?", { name: project.name }),
      message: t(
        "It is brought down first and stays down. Named volumes keep the old project name: after up, the stack gets new, empty ones, unless the file names them (name: or external).",
      ),
      confirmLabel: t("Rename"),
      initial: project.name,
    });
    if (!name || name === project.name) return;
    await changeStack(t("Renaming…"), async () => {
      const accepted = await api.renameProject(id, name);
      await waitForJob(accepted.job);
      navigate(`/projects/${accepted.project_id}`, { replace: true });
    });
  };

  const duplicateStack = async (): Promise<void> => {
    if (!project) return;
    const name = await askName(confirm, {
      title: t("Duplicate stack {name}?", { name: project.name }),
      message: t(
        "Copies its folder (or its Compose files in a shared folder). Nothing starts. Change fixed container names and host ports before you bring the copy up.",
      ),
      confirmLabel: t("Duplicate"),
      initial: `${project.name}-copy`,
    });
    if (!name) return;
    await changeStack(t("Duplicating…"), async () => {
      const accepted = await api.duplicateProject(id, name);
      await waitForJob(accepted.job);
      setStackNotice(
        <>
          {t("Copied as")} <Link to={`/projects/${accepted.project_id}`}>{name}</Link>.
        </>,
      );
    });
  };

  if (loadError) {
    return <div className="error">{t("Failed to load: {error}", { error: loadError })}</div>;
  }
  if (!project) return <div>{t("Loading…")}</div>;

  const dirty = compose !== originalCompose;
  const running = project.containers.filter((container) => container.state === "running").length;
  // `up` recreates the containers of services whose config changed, so a file
  // newer than every container was most likely not deployed yet.
  const newestContainer = Math.max(
    ...project.containers.map((container) => Date.parse(container.created_at)),
  );
  const changedSinceDeploy =
    project.containers.length > 0 && Date.parse(project.modified_at) > newestContainer;
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
          <ChevronLeft size={15} /> {t("Projects")}
        </Link>
      </div>
      <div className="row-between">
        <h1>{project.name}</h1>
        <div className="button-row inline">
          {stackBusy && <span className="muted">{stackBusy}</span>}
          <button type="button" className="secondary" onClick={() => setShowLogs(true)}>
            <ScrollText size={15} /> {t("Stack logs")}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={stackBusy !== null || busyAction !== undefined}
            onClick={renameStack}
          >
            <PenLine size={15} /> {t("Rename")}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={stackBusy !== null}
            onClick={duplicateStack}
          >
            <Copy size={15} /> {t("Duplicate")}
          </button>
          <button
            type="button"
            className="secondary"
            disabled={stackBusy !== null || busyAction !== undefined}
            onClick={deleteStack}
          >
            <Trash2 size={15} /> {t("Delete")}
          </button>
        </div>
      </div>
      <div className="muted">
        <code>{project.relative_path}</code>
      </div>

      {stackNotice && (
        <div className="output ok" style={{ padding: "0.75rem" }}>
          {stackNotice}
        </div>
      )}
      <section className="section">
        <h2>{t("Actions")}</h2>
        <div className="button-row">
          {ACTIONS.map((action) => {
            const Icon = ACTION_ICONS[action];
            return (
              <button
                key={action}
                type="button"
                disabled={busyAction !== undefined}
                title={t(ACTION_HINTS[action])}
                onClick={() => runAction(action)}
              >
                <Icon size={15} />{" "}
                {busyAction === action
                  ? `${ACTION_TEXT[action] ?? action}…`
                  : (ACTION_TEXT[action] ?? action)}
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
              <span>
                {isActive(lastJob)
                  ? `${t(JOB_STATUS_TEXT[lastJob.status])}…`
                  : t(JOB_STATUS_TEXT[lastJob.status])}
              </span>
            </div>
            {lastJob.output && <pre>{lastJob.output}</pre>}
            {lastJob.error && !lastJob.output && <pre className="stderr">{lastJob.error}</pre>}
          </div>
        )}
      </section>

      <section className="section">
        <h2>
          {t("Containers")}{" "}
          <span className="muted">
            {t("{running} of {total} running", { running, total: project.containers.length })}
          </span>
        </h2>
        {changedSinceDeploy && (
          <div
            className="notice"
            title={t("Compose file saved {saved}. Newest container created {created}.", {
              saved: formatDate(project.modified_at),
              created: formatDate(new Date(newestContainer).toISOString()),
            })}
          >
            {t(
              "The Compose file changed after these containers were created. Run up to apply it.",
            )}
          </div>
        )}
        {project.containers.length === 0 ? (
          <div className="empty">
            {t("No containers for this stack. Deploy it with")} <strong>up</strong>.
          </div>
        ) : (
          <table className="projects-table">
            <thead>
              <tr>
                <SortHeader sorting={sorting} column="name">
                  {t("Name")}
                </SortHeader>
                <SortHeader sorting={sorting} column="service">
                  {t("Service")}
                </SortHeader>
                <SortHeader sorting={sorting} column="image">
                  {t("Image")}
                </SortHeader>
                <SortHeader sorting={sorting} column="status">
                  {t("Status")}
                </SortHeader>
                <SortHeader sorting={sorting} column="uptime">
                  {t("Uptime")}
                </SortHeader>
                <th>{t("Ports")}</th>
              </tr>
            </thead>
            <tbody>
              {sorting.rows.map((container) => (
                <tr key={container.id}>
                  <td>
                    <Link className="row-name" to={`/containers/${container.id}`}>
                      {container.name}
                    </Link>
                  </td>
                  <td>{container.compose_service ?? "—"}</td>
                  <td>
                    <ImageName image={container.image} version={container.image_version} />
                  </td>
                  <td>
                    <span className={`badge ${container.state}`}>
                      <Circle size={8} fill="currentColor" /> {t(containerStateLabel(container.state))}
                    </span>{" "}
                    <HealthBadge health={container.health} />
                    {container.restart_count > 0 && (
                      <div className="muted" title={t("Restarts since the container was created")}>
                        {container.restart_count === 1
                          ? t("1 restart")
                          : t("{count} restarts", { count: container.restart_count })}
                      </div>
                    )}
                  </td>
                  <td>
                    <Uptime container={container} />
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
        {user?.is_admin ? (
          <div className="tabs">
            <button
              type="button"
              className={`tab ${fileTab === "compose" ? "active" : ""}`}
              onClick={() => setFileTab("compose")}
            >
              {t("Compose file")}
            </button>
            <button
              type="button"
              className={`tab ${fileTab === "env" ? "active" : ""}`}
              title={t("Variables Compose substitutes into the file")}
              onClick={() => {
                setFileTab("env");
                setEnvOpened(true);
              }}
            >
              .env
            </button>
          </div>
        ) : (
          <h2>{t("Compose file")}</h2>
        )}
        {envOpened && (
          <div hidden={fileTab !== "env"}>
            <EnvFile projectId={id} />
          </div>
        )}
        <div hidden={fileTab !== "compose"}>
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
          <Suspense fallback={<div className="empty">{t("Loading editor…")}</div>}>
            <YamlEditor
              value={compose}
              onChange={setCompose}
              onSave={() => {
                if (dirty && !saving) void save();
              }}
            />
          </Suspense>
          <div className="button-row">
            <button type="button" onClick={save} disabled={!dirty || saving}>
              <Save size={15} /> {saving ? t("Saving…") : t("Save")}
            </button>
            <button
              type="button"
              className="secondary"
              onClick={() => setCompose(originalCompose)}
              disabled={!dirty || saving}
            >
              <Undo2 size={15} /> {t("Revert")}
            </button>
            {savedAt && !dirty && <span className="muted">{savedAt}</span>}
          </div>
          {saveError && <div className="error">{saveError}</div>}
        </div>
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

/** Editor for the `.env` next to the Compose file. Same validate, back up, write flow. */
function EnvFile({ projectId }: { projectId: string }) {
  const t = useT();
  const [content, setContent] = useState<string | null>(null);
  const [original, setOriginal] = useState("");
  const [exists, setExists] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);

  useEffect(() => {
    api
      .getEnv(projectId)
      .then((envFile) => {
        setContent(envFile.content);
        setOriginal(envFile.content);
        setExists(envFile.exists);
      })
      .catch((loadError: Error) => setError(loadError.message));
  }, [projectId]);

  const save = async (): Promise<void> => {
    if (content === null) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.putEnv(projectId, content);
      setOriginal(content);
      setExists(true);
      setSavedAt(
        saved.backup_path ? t("Saved. Backup: {path}", { path: saved.backup_path }) : t("Saved."),
      );
    } catch (saveError) {
      setError((saveError as Error).message);
    } finally {
      setSaving(false);
    }
  };

  if (content === null) {
    return error ? (
      <div className="error">{error}</div>
    ) : (
      <div className="empty">{t("Loading…")}</div>
    );
  }
  const dirty = content !== original;

  return (
    <>
      <div className="muted" style={{ marginBottom: "0.5rem" }}>
        {exists
          ? t("Stacks in the same folder share this file. Changes apply on the next up.")
          : t("No .env in this folder yet. Saving creates it.")}
      </div>
      <Suspense fallback={<div className="empty">{t("Loading editor…")}</div>}>
        <YamlEditor
          value={content}
          onChange={setContent}
          onSave={() => {
            if (dirty && !saving) void save();
          }}
          height="320px"
          plain
        />
      </Suspense>
      <div className="button-row">
        <button type="button" onClick={save} disabled={!dirty || saving}>
          <Save size={15} /> {saving ? t("Saving…") : t("Save")}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={() => setContent(original)}
          disabled={!dirty || saving}
        >
          <Undo2 size={15} /> {t("Revert")}
        </button>
        {savedAt && !dirty && <span className="muted">{savedAt}</span>}
      </div>
      {error && <div className="error">{error}</div>}
    </>
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
  const t = useT();
  // One sentence, split around the image so it stays in place in every language.
  const [updateBefore, updateAfter] = t("Update {image}:").split("{image}");
  // Same-major first: it is the safer upgrade; a new major may need config changes.
  const choices: [string, string][] = [];
  if (update?.newest_same_major_tag) choices.push([update.newest_same_major_tag, msg("same major")]);
  if (update?.newest_tag && update.newest_tag !== update.newest_same_major_tag) {
    choices.push([update.newest_tag, msg("newest")]);
  }

  return (
    <div className="output" style={{ padding: "0.75rem" }}>
      {applied ? (
        <div className="button-row">
          <span>
            {t("Image changed to")} <code>{imageRepo(image)}:{applied}</code>{" "}
            {t("(not saved yet). Review it below, then:")}
          </span>
          <button type="button" disabled={busy} onClick={onDeploy}>
            <Play size={15} /> {t("Save & deploy")}
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={onDismiss}>
            {t("Close")}
          </button>
        </div>
      ) : (
        <div className="button-row">
          <span>
            <ArrowUpCircle size={14} /> {updateBefore}
            <code>{image}</code>
            {updateAfter}
          </span>
          {choices.length === 0 ? (
            <span className="muted">
              {t("no newer tag recorded. Run an update check first.")}
            </span>
          ) : (
            choices.map(([tag, label]) => (
              <button key={tag} type="button" className="small" onClick={() => onApply(tag)}>
                {t("Use {tag}", { tag })} <span className="muted">({t(label)})</span>
              </button>
            ))
          )}
          <button type="button" className="secondary small" onClick={onDismiss}>
            {t("Cancel")}
          </button>
        </div>
      )}
      {note && <div className="error">{note}</div>}
    </div>
  );
}
