import { Plus } from "lucide-react";
import { lazy, Suspense, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";

const YamlEditor = lazy(() => import("../components/YamlEditor"));

const TEMPLATE = `services:
  app:
    image: nginx:latest
    restart: unless-stopped
    ports:
      - "8080:80"
`;

// Same rule as the backend: it becomes the folder and Compose project name.
const NAME_PATTERN = /^[a-z0-9][a-z0-9_-]*$/;

/** Create `<repo>/<name>/docker-compose.yml` from the browser. */
export default function NewProject() {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [content, setContent] = useState(TEMPLATE);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const nameValid = NAME_PATTERN.test(name);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const project = await api.createProject(name, content);
      navigate(`/projects/${project.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="row-between">
        <h1>New stack</h1>
        <Link to="/projects">Back to projects</Link>
      </div>
      <form className="new-stack-form" onSubmit={onSubmit}>
        <label>
          Name{" "}
          <input
            type="text"
            value={name}
            placeholder="my-stack"
            maxLength={64}
            onChange={(e) => setName(e.target.value)}
            autoFocus
          />
          <div className="muted">
            Creates <code>{name || "<name>"}/docker-compose.yml</code> in the repo. Lowercase
            letters, digits, <code>-</code> and <code>_</code> only.
          </div>
        </label>
        <Suspense fallback={<div className="empty">Loading editor…</div>}>
          <YamlEditor value={content} onChange={setContent} />
        </Suspense>
        {error && <div className="error">{error}</div>}
        <div className="button-row">
          <button type="submit" disabled={!nameValid || busy}>
            <Plus size={15} /> Create stack
          </button>
        </div>
      </form>
    </div>
  );
}
