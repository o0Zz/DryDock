import {
  ArrowDownCircle,
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
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import LogPanel from "../components/LogPanel";
import type { ActionResult, Project } from "../types";

// CodeMirror is by far the heaviest dependency in the bundle and is only
// needed on this page, so it loads on demand.
const YamlEditor = lazy(() => import("../components/YamlEditor"));

type Action = "up" | "down" | "pull" | "restart" | "stop";
const ACTIONS: Action[] = ["up", "down", "pull", "restart", "stop"];
const ACTION_ICONS: Record<Action, LucideIcon> = {
  up: Play,
  down: ArrowDownCircle,
  pull: Download,
  restart: RotateCw,
  stop: Square,
};

// `down` removes containers and networks, so it gets a confirmation step.
const CONFIRM: Partial<Record<Action, string>> = {
  down: "Bring this stack down? Its containers and networks will be removed.",
};

export default function ProjectDetail() {
  const { id = "" } = useParams();
  const [project, setProject] = useState<Project | null>(null);
  const [compose, setCompose] = useState<string>("");
  const [originalCompose, setOriginalCompose] = useState<string>("");
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<Action | null>(null);
  const [actionResult, setActionResult] = useState<ActionResult | null>(null);
  const [showLogs, setShowLogs] = useState(false);

  const reloadProject = useCallback(async () => {
    setProject(await api.getProject(id));
  }, [id]);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.getProject(id), api.getCompose(id)])
      .then(([p, c]) => {
        if (cancelled) return;
        setProject(p);
        setCompose(c.content);
        setOriginalCompose(c.content);
      })
      .catch((e: Error) => !cancelled && setLoadError(e.message));
    return () => {
      cancelled = true;
    };
  }, [id]);

  const save = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    try {
      const res = await api.putCompose(id, compose);
      setOriginalCompose(compose);
      setSavedAt(`Saved. Backup: ${res.backup_path}`);
    } catch (e) {
      setSaveError((e as Error).message);
    } finally {
      setSaving(false);
    }
  }, [id, compose]);

  const runAction = useCallback(
    async (action: Action) => {
      const question = CONFIRM[action];
      if (question && !window.confirm(question)) return;

      setBusyAction(action);
      setActionResult(null);
      try {
        const result = await api.runAction(id, action);
        setActionResult(result);
        // Container state almost always changed; refresh what we show.
        await reloadProject().catch(() => undefined);
      } catch (e) {
        setActionResult({
          action,
          exit_code: -1,
          stdout: "",
          stderr: (e as Error).message,
        });
      } finally {
        setBusyAction(null);
      }
    },
    [id, reloadProject],
  );

  if (loadError) return <div className="error">Failed to load: {loadError}</div>;
  if (!project) return <div>Loading…</div>;

  const dirty = compose !== originalCompose;
  const running = project.containers.filter((c) => c.state === "running").length;

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
          {ACTIONS.map((a) => {
            const Icon = ACTION_ICONS[a];
            return (
              <button
                key={a}
                type="button"
                disabled={busyAction !== null}
                onClick={() => runAction(a)}
              >
                <Icon size={15} /> {busyAction === a ? `${a}…` : a}
              </button>
            );
          })}
        </div>
        {actionResult && (
          <div className={actionResult.exit_code === 0 ? "output ok" : "output fail"}>
            <div className="output-header">
              <strong>{actionResult.action}</strong>
              <span>exit {actionResult.exit_code}</span>
            </div>
            {actionResult.stdout && <pre>{actionResult.stdout}</pre>}
            {actionResult.stderr && <pre className="stderr">{actionResult.stderr}</pre>}
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
              {project.containers.map((c) => (
                <tr key={c.id}>
                  <td>{c.name}</td>
                  <td>{c.compose_service ?? "—"}</td>
                  <td>{c.image}</td>
                  <td>
                    <span className={`badge ${c.state}`}>
                      <Circle size={8} fill="currentColor" /> {c.state}
                    </span>
                  </td>
                  <td>
                    {c.ports
                      .filter((p) => p.public_port)
                      .map((p) => `${p.public_port}→${p.private_port}/${p.protocol}`)
                      .join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="section">
        <h2>Compose file</h2>
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
