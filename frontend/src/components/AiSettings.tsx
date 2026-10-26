import { ExternalLink, ListRestart, LogIn, Save, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import { msg, useT } from "../i18n";
import type { AiConfig, AiProvider, AiProviderId, CopilotDevice } from "../types";
import { useConfirm } from "./ConfirmDialog";

const NAMES: Record<AiProviderId, string> = {
  openai: "OpenAI",
  anthropic: "Anthropic",
  copilot: "GitHub Copilot",
};

const HINTS: Record<AiProviderId, string> = {
  openai: msg(
    "An API key from platform.openai.com. Change the base URL to use an OpenAI-compatible server instead (Ollama, LM Studio, LiteLLM).",
  ),
  anthropic: msg("An API key from console.anthropic.com."),
  copilot: msg(
    "Sign in with a GitHub account that has a Copilot plan. DryDock keeps the GitHub sign-in, not a key.",
  ),
};

/** AI providers for the Compose editor's assistant (admin only). */
export default function AiSettings() {
  const t = useT();
  const [config, setConfig] = useState<AiConfig | null>(null);
  // The provider shown can differ from the active one until it is set up.
  const [selected, setSelected] = useState<AiProviderId | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getAi()
      .then((loaded) => {
        setConfig(loaded);
        setSelected(loaded.active);
      })
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  async function activate(next: AiConfig, provider: AiProviderId | null): Promise<void> {
    setConfig(next);
    const ready = provider === null || next.providers.some((p) => p.id === provider && p.configured);
    if (ready && next.active !== provider) setConfig(await api.setAiActive(provider));
  }

  async function choose(provider: AiProviderId | null): Promise<void> {
    setError(null);
    setSelected(provider);
    try {
      if (config) await activate(config, provider);
    } catch (chooseError) {
      setError((chooseError as Error).message);
    }
  }

  // A provider just set up becomes the one in use.
  async function changed(next: AiConfig): Promise<void> {
    try {
      await activate(next, selected);
    } catch (activateError) {
      setError((activateError as Error).message);
    }
  }

  if (!config) {
    return error ? <div className="error">{error}</div> : <div>{t("Loading…")}</div>;
  }
  const shown = config.providers.find((provider) => provider.id === selected);

  return (
    <section className="section">
      <h2>{t("AI assistant")}</h2>
      <p className="muted">
        {t(
          "The Compose editor gets a chat: ask for a change and review it before you save. The file is sent to the provider chosen here; the .env file never is.",
        )}
      </p>
      <label className="field">
        {t("Provider")}
        <select
          value={selected ?? ""}
          onChange={(event) => choose((event.target.value || null) as AiProviderId | null)}
        >
          <option value="">{t("None (assistant off)")}</option>
          {config.providers.map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.configured
                ? NAMES[provider.id]
                : `${NAMES[provider.id]} (${t("not set up")})`}
            </option>
          ))}
        </select>
      </label>
      {error && <div className="error">{error}</div>}
      {shown && <ProviderForm key={shown.id} provider={shown} onChange={changed} />}
    </section>
  );
}

function ProviderForm({
  provider,
  onChange,
}: {
  provider: AiProvider;
  onChange: (config: AiConfig) => void;
}) {
  const t = useT();
  const confirm = useConfirm();
  const [apiKey, setApiKey] = useState("");
  const [model, setModel] = useState(provider.model);
  const [baseUrl, setBaseUrl] = useState(provider.base_url);
  const [models, setModels] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const isCopilot = provider.id === "copilot";

  const dirty =
    apiKey !== "" || model !== provider.model || (!isCopilot && baseUrl !== provider.base_url);

  async function run(action: () => Promise<void>): Promise<void> {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await action();
    } catch (actionError) {
      setError((actionError as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const save = () =>
    run(async () => {
      const config = await api.setAiProvider(provider.id, {
        model,
        api_key: apiKey,
        ...(provider.id === "openai" ? { base_url: baseUrl } : {}),
      });
      const saved = config.providers.find((candidate) => candidate.id === provider.id);
      setApiKey("");
      if (saved) setModel(saved.model);
      onChange(config);
      setNotice(t("Saved."));
    });

  const loadModels = () =>
    run(async () => {
      setModels(await api.listAiModels(provider.id));
    });

  const remove = async (): Promise<void> => {
    const accepted = await confirm({
      title: t("Remove {provider}?", { provider: NAMES[provider.id] }),
      message: isCopilot
        ? t("DryDock forgets the GitHub sign-in.")
        : t("DryDock forgets the API key."),
      confirmLabel: t("Remove"),
      tone: "danger",
    });
    if (accepted) await run(async () => onChange(await api.removeAiProvider(provider.id)));
  };

  const listId = `ai-models-${provider.id}`;

  return (
    <div className="subsection">
      <p className="muted">{t(HINTS[provider.id])}</p>
      {isCopilot ? (
        <CopilotSignIn provider={provider} onChange={onChange} />
      ) : (
        <label className="field">
          {t("API key")}
          <input
            type="password"
            autoComplete="off"
            value={apiKey}
            placeholder={provider.configured ? t("Stored. Type a new one to replace it.") : ""}
            onChange={(event) => setApiKey(event.target.value)}
          />
        </label>
      )}
      {provider.id === "openai" && (
        <label className="field">
          {t("Base URL")}
          <input
            type="text"
            value={baseUrl}
            placeholder="https://api.openai.com/v1"
            onChange={(event) => setBaseUrl(event.target.value)}
          />
        </label>
      )}
      <label className="field">
        {t("Model")}
        <input
          type="text"
          list={listId}
          value={model}
          onChange={(event) => setModel(event.target.value)}
        />
        <datalist id={listId}>
          {models.map((name) => (
            <option key={name} value={name} />
          ))}
        </datalist>
      </label>
      <div className="button-row">
        <button type="button" onClick={save} disabled={!dirty || busy || (isCopilot && !provider.configured)}>
          <Save size={15} /> {t("Save")}
        </button>
        <button
          type="button"
          className="secondary"
          onClick={loadModels}
          disabled={!provider.configured || busy}
          title={t("Ask the provider which models this key can use")}
        >
          <ListRestart size={15} /> {t("Load models")}
        </button>
        {provider.configured && (
          <button type="button" className="secondary" onClick={remove} disabled={busy}>
            <Trash2 size={15} /> {t("Remove")}
          </button>
        )}
        {models.length > 0 && (
          <span className="muted">{t("{count} models in the list.", { count: models.length })}</span>
        )}
        {notice && <span className="muted">{notice}</span>}
      </div>
      {error && <div className="error">{error}</div>}
    </div>
  );
}

/** GitHub's device sign-in: show the code, open GitHub, poll until the user is done. */
function CopilotSignIn({
  provider,
  onChange,
}: {
  provider: AiProvider;
  onChange: (config: AiConfig) => void;
}) {
  const t = useT();
  const [device, setDevice] = useState<CopilotDevice | null>(null);
  const [error, setError] = useState<string | null>(null);
  const timer = useRef<number | undefined>(undefined);

  // Stop polling when the page closes.
  useEffect(() => () => window.clearTimeout(timer.current), []);

  async function poll(interval: number): Promise<void> {
    try {
      const result = await api.pollCopilotSignIn();
      if (result.status === "pending") {
        timer.current = window.setTimeout(() => poll(interval), interval * 1000);
        return;
      }
      setDevice(null);
      if (result.status === "done") onChange(await api.getAi());
      else if (result.status === "denied") setError(t("The sign-in was refused on GitHub."));
      else setError(t("The code expired. Start again."));
    } catch (pollError) {
      setDevice(null);
      setError((pollError as Error).message);
    }
  }

  async function start(): Promise<void> {
    setError(null);
    window.clearTimeout(timer.current);
    try {
      const started = await api.startCopilotSignIn();
      setDevice(started);
      timer.current = window.setTimeout(() => poll(started.interval), started.interval * 1000);
    } catch (startError) {
      setError((startError as Error).message);
    }
  }

  return (
    <div className="field">
      {provider.account && !device && (
        <span>{t("Signed in as {account}.", { account: provider.account })}</span>
      )}
      {device ? (
        <div className="output padded">
          <div>
            {t("Open GitHub and enter this code:")} <code className="device-code">{device.user_code}</code>
          </div>
          <div className="button-row">
            <a className="button" href={device.verification_uri} target="_blank" rel="noreferrer">
              <ExternalLink size={15} /> {t("Open GitHub")}
            </a>
            <span className="muted">{t("Waiting for GitHub…")}</span>
          </div>
        </div>
      ) : (
        <div className="button-row">
          <button type="button" className="secondary" onClick={start}>
            <LogIn size={15} /> {provider.account ? t("Sign in again") : t("Sign in with GitHub")}
          </button>
        </div>
      )}
      {error && <div className="error">{error}</div>}
    </div>
  );
}
