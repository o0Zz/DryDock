import { Plus } from "lucide-react";
import { lazy, Suspense, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useT } from "../i18n";
import {
  CERT_CHOICES,
  defaultCert,
  STACK_TEMPLATES,
  type CertSetup,
  type StackTemplate,
} from "../stackTemplates";

const YamlEditor = lazy(() => import("../components/YamlEditor"));

// Same rule as the backend: it becomes the folder and Compose project name.
const NAME_PATTERN = /^[a-z0-9][a-z0-9_-]*$/;
// A DNS provider's name as Traefik (lego) spells it.
const PROVIDER_PATTERN = /^[a-z0-9][a-z0-9.-]*$/;

/** Create `<repo>/<name>/docker-compose.yml` from the browser. */
export default function NewProject() {
  const t = useT();
  const navigate = useNavigate();
  const { user } = useAuth();
  // `?template=traefik` arrives from the Proxy page.
  const [searchParams] = useSearchParams();
  const initial =
    STACK_TEMPLATES.find((candidate) => candidate.id === searchParams.get("template")) ??
    STACK_TEMPLATES[0];
  const [templateId, setTemplateId] = useState(initial.id);
  const [cert, setCert] = useState<CertSetup>(defaultCert(initial));
  const [name, setName] = useState(initial.name);
  const [content, setContent] = useState(initial.compose(defaultCert(initial)));
  const [domain, setDomain] = useState("");
  // DryDock's own image: the proxy templates run their sync from it.
  const [image, setImage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const template = STACK_TEMPLATES.find((candidate) => candidate.id === templateId)!;
  const nameValid = NAME_PATTERN.test(name);
  const certValid = !template.certs || PROVIDER_PATTERN.test(cert.provider);

  useEffect(() => {
    api
      .getProxy()
      .then((proxy) => {
        setDomain(proxy.domain);
        setImage(proxy.drydock_image);
      })
      .catch(() => undefined);
  }, []);

  // The template is shown before the image is known; fill it in as soon as it is.
  useEffect(() => {
    if (image) setContent((current) => current.replaceAll("{image}", image));
  }, [image, templateId, cert]);

  function render(next: StackTemplate, nextCert: CertSetup): void {
    const compose = next.compose(nextCert);
    setContent(image ? compose.replaceAll("{image}", image) : compose);
  }

  function pickTemplate(id: string): void {
    const next = STACK_TEMPLATES.find((candidate) => candidate.id === id)!;
    const nextCert = defaultCert(next);
    setTemplateId(id);
    setCert(nextCert);
    render(next, nextCert);
    // Keep a name the user typed; replace only the previous template's suggestion.
    if (!name || name === template.name) setName(next.name);
  }

  function pickCert(nextCert: CertSetup): void {
    setCert(nextCert);
    render(template, nextCert);
  }

  async function onSubmit(event: FormEvent): Promise<void> {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const project = await api.createProject(name, content);
      if (template.env && user?.is_admin) {
        await api.putEnv(project.id, template.env(cert).replace("{domain}", domain || "example.org"));
      }
      navigate(`/projects/${project.id}`);
    } catch (createError) {
      setError((createError as Error).message);
      setBusy(false);
    }
  }

  const certChoice = CERT_CHOICES.find((choice) => choice.id === cert.choice);

  return (
    <div>
      <div className="row-between">
        <h1>{t("New stack")}</h1>
        <Link to="/projects">{t("Back to projects")}</Link>
      </div>
      <form className="new-stack-form" onSubmit={onSubmit}>
        <label>
          {t("Template")}{" "}
          <select value={templateId} onChange={(event) => pickTemplate(event.target.value)}>
            {STACK_TEMPLATES.map((candidate) => (
              <option key={candidate.id} value={candidate.id}>
                {t(candidate.label)}
              </option>
            ))}
          </select>
          <div className="muted">
            {t(template.description)}
            {template.env &&
              (user?.is_admin
                ? ` ${t("Its .env is created too: fill it in before the first up.")}`
                : ` ${t("It needs a .env: ask an admin to fill it in.")}`)}
          </div>
        </label>
        {template.certs && (
          <label>
            {t("Certificates")}{" "}
            <select
              value={cert.choice}
              onChange={(event) => {
                const choice = event.target.value as CertSetup["choice"];
                pickCert({ choice, provider: choice === "other" ? "" : choice });
              }}
            >
              {CERT_CHOICES.filter((choice) => template.certs?.includes(choice.id)).map(
                (choice) => (
                  <option key={choice.id} value={choice.id}>
                    {t(choice.label)}
                  </option>
                ),
              )}
            </select>
            {cert.choice === "other" && (
              <input
                type="text"
                placeholder={t("provider name, e.g. gandiv5")}
                value={cert.provider}
                onChange={(event) =>
                  pickCert({ choice: "other", provider: event.target.value.trim().toLowerCase() })
                }
              />
            )}
            {certChoice && <div className="muted">{t(certChoice.description)}</div>}
          </label>
        )}
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
          <button type="submit" disabled={!nameValid || !certValid || busy}>
            <Plus size={15} /> {t("Create stack")}
          </button>
        </div>
      </form>
    </div>
  );
}
