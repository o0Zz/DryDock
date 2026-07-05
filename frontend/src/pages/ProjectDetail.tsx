import {
  ArrowDownCircle,
  ChevronLeft,
  Download,
  Play,
  RotateCw,
  Save,
  Square,
  Undo2,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { ActionResult, Project } from "../types";

type Action = "up" | "down" | "pull" | "restart" | "stop";
const ACTIONS: Action[] = ["up", "down", "pull", "restart", "stop"];
const ACTION_ICONS: Record<Action, LucideIcon> = {
  up: Play,
  down: ArrowDownCircle,
  pull: Download,
  restart: RotateCw,
  stop: Square,
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
      setBusyAction(action);
      setActionResult(null);
      try {
        const result = await api.runAction(id, action);
        setActionResult(result);
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
    [id],
  );

  if (loadError) return <div className="error">Failed to load: {loadError}</div>;
  if (!project) return <div>Loading…</div>;

  const dirty = compose !== originalCompose;

  return (
    <div>
      <div className="crumb">
        <Link to="/projects"><ChevronLeft size={15} /> Projects</Link>
      </div>
      <h1>{project.name}</h1>
      <div className="muted"><code>{project.relative_path}</code></div>

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
        <h2>Compose file</h2>
        <textarea
          className="yaml-editor"
          value={compose}
          onChange={(e) => setCompose(e.target.value)}
          spellCheck={false}
          rows={24}
        />
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
    </div>
  );
}
