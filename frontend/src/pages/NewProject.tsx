import { Plus } from "lucide-react";
import { lazy, Suspense, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useT } from "../i18n";

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
  const t = useT();
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [content, setContent] = useState(TEMPLATE);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const nameValid = NAME_PATTERN.test(name);

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const project = await api.createProject(name, content);
      navigate(`/projects/${project.id}`);
    } catch (createError) {
      setError((createError as Error).message);
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="row-between">
        <h1>{t("New stack")}</h1>
        <Link to="/projects">{t("Back to projects")}</Link>
      </div>
      <form className="new-stack-form" onSubmit={onSubmit}>
        <label>
          {t("Name")}{" "}
          <input
            type="text"
            value={name}
            placeholder={t("my-stack")}
            maxLength={64}
            onChange={(event) => setName(event.target.value)}
            autoFocus
          />
          <div className="muted">
            {t("Creates")} <code>{name || t("<name>")}/docker-compose.yml</code>{" "}
            {t("in the repo. Lowercase letters, digits,")} <code>-</code> {t("and")}{" "}
            <code>_</code> {t("only.")}
          </div>
        </label>
        <Suspense fallback={<div className="empty">{t("Loading editor…")}</div>}>
          <YamlEditor value={content} onChange={setContent} />
        </Suspense>
        {error && <div className="error">{error}</div>}
        <div className="button-row">
          <button type="submit" disabled={!nameValid || busy}>
            <Plus size={15} /> {t("Create stack")}
          </button>
        </div>
      </form>
    </div>
  );
}
