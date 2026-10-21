import { Check, Eraser, Loader2, SendHorizontal, Sparkles, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { useT } from "../i18n";
import { changesOnly, lineDiff } from "../lineDiff";
import type { AiConfig, AiMessage } from "../types";

const NAMES = { openai: "OpenAI", anthropic: "Anthropic", copilot: "GitHub Copilot" };

interface Entry {
  role: AiMessage["role"];
  /** The user's text, or the assistant's explanation without the file. */
  text: string;
  /** The proposed file and the file it was asked against. */
  proposal?: { content: string; base: string; error: string | null };
  applied?: boolean;
}

/** What the model said, file included, so the next turn sees its own answer. */
function asMessage(entry: Entry): AiMessage {
  const file = entry.proposal ? `\n\n\`\`\`yaml\n${entry.proposal.content}\`\`\`` : "";
  return { role: entry.role, content: entry.text + file };
}

/** Chat beside the Compose editor: ask for a change, review it, apply it to the editor. */
export default function ComposeAssistant({
  content,
  onApply,
  onClose,
}: {
  content: string;
  onApply: (next: string) => void;
  onClose: () => void;
}) {
  const t = useT();
  const { user } = useAuth();
  const [config, setConfig] = useState<AiConfig | null>(null);
  const [entries, setEntries] = useState<Entry[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api
      .getAi()
      .then(setConfig)
      .catch((loadError: Error) => setError(loadError.message));
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ block: "nearest" });
  }, [entries, busy]);

  const provider = config?.providers.find((candidate) => candidate.id === config.active);

  async function send(): Promise<void> {
    const text = input.trim();
    if (!text || busy) return;
    const history = [...entries, { role: "user" as const, text }];
    setEntries(history);
    setInput("");
    setBusy(true);
    setError(null);
    try {
      const answer = await api.assistCompose(content, history.map(asMessage));
      setEntries([
        ...history,
        {
          role: "assistant",
          text: answer.reply,
          proposal:
            answer.content === null
              ? undefined
              : { content: answer.content, base: content, error: answer.error },
        },
      ]);
    } catch (sendError) {
      setError((sendError as Error).message);
      // Back in the box, so the request is not lost.
      setEntries(entries);
      setInput(text);
    } finally {
      setBusy(false);
    }
  }

  function apply(index: number): void {
    const proposal = entries[index].proposal;
    if (!proposal) return;
    onApply(proposal.content);
    setEntries((previous) =>
      previous.map((entry, at) => (at === index ? { ...entry, applied: true } : entry)),
    );
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
      event.preventDefault();
      void send();
    }
  }

  return (
    <aside className="assistant">
      <div className="assistant-header">
        <strong>
          <Sparkles size={15} /> {t("AI assistant")}
        </strong>
        {provider && (
          <span className="muted assistant-model" title={provider.model}>
            {NAMES[provider.id]} · {provider.model}
          </span>
        )}
        <div className="button-row inline">
          {entries.length > 0 && (
            <button
              type="button"
              className="secondary small icon-only"
              title={t("New conversation")}
              disabled={busy}
              onClick={() => setEntries([])}
            >
              <Eraser size={14} />
            </button>
          )}
          <button
            type="button"
            className="secondary small icon-only"
            title={t("Close")}
            onClick={onClose}
          >
            <X size={14} />
          </button>
        </div>
      </div>

      <div className="assistant-body">
        {config && !provider && (
          <div className="empty">
            {user?.is_admin ? (
              <>
                {t("No AI provider is set up yet.")}{" "}
                <Link to="/settings?tab=ai">{t("Set one up in Settings.")}</Link>
              </>
            ) : (
              t("No AI provider is set up yet. Ask an admin to set one up in Settings.")
            )}
          </div>
        )}
        {provider && entries.length === 0 && (
          <div className="muted">
            {t(
              "Ask for a change, for example: \"add a healthcheck to web\" or \"put the database on its own network\". The answer is not saved until you apply it and save.",
            )}
          </div>
        )}
        {entries.map((entry, index) => (
          <div key={index} className={`assistant-message ${entry.role}`}>
            {entry.text && <div className="assistant-text">{entry.text}</div>}
            {entry.proposal && (
              <Proposal
                {...entry.proposal}
                current={content}
                applied={entry.applied ?? false}
                onApply={() => apply(index)}
              />
            )}
          </div>
        ))}
        {busy && (
          <div className="assistant-message assistant muted">
            <Loader2 size={14} className="spin" /> {t("Thinking…")}
          </div>
        )}
        {error && <div className="error">{error}</div>}
        <div ref={bottom} />
      </div>

      <div className="assistant-input">
        <textarea
          rows={3}
          value={input}
          disabled={!provider}
          placeholder={t("Describe the change you want…")}
          onChange={(event) => setInput(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <button
          type="button"
          onClick={() => void send()}
          disabled={!provider || busy || !input.trim()}
          title={t("Send (Enter). Shift+Enter for a new line.")}
        >
          <SendHorizontal size={15} />
        </button>
      </div>
    </aside>
  );
}

function Proposal({
  content,
  base,
  error,
  current,
  applied,
  onApply,
}: {
  content: string;
  base: string;
  error: string | null;
  current: string;
  applied: boolean;
  onApply: () => void;
}) {
  const t = useT();
  const diff = useMemo(() => lineDiff(base, content), [base, content]);
  const added = diff?.filter((line) => line.kind === "added").length ?? 0;
  const removed = diff?.filter((line) => line.kind === "removed").length ?? 0;
  const shown = useMemo(() => (diff ? changesOnly(diff) : null), [diff]);
  // The editor moved on since the question: applying replaces those edits too.
  const stale = !applied && current !== base && current !== content;

  return (
    <div className="assistant-proposal">
      <div className="assistant-proposal-header">
        <span>
          {t("Proposed file")}{" "}
          <span className="diff-added">+{added}</span> <span className="diff-removed">−{removed}</span>
        </span>
        {applied || current === content ? (
          <span className="muted">
            <Check size={14} /> {t("In the editor, not saved yet")}
          </span>
        ) : (
          <button type="button" className="small" onClick={onApply}>
            {t("Apply to editor")}
          </button>
        )}
      </div>
      {error && <div className="error">{t("This file will not save: {error}", { error })}</div>}
      {stale && (
        <div className="muted">
          {t("The editor changed since this answer. Applying it replaces those edits.")}
        </div>
      )}
      {shown ? (
        <pre className="diff">
          {shown.map((line, index) =>
            line === null ? (
              <div key={index} className="diff-gap">
                ⋯
              </div>
            ) : (
              <div key={index} className={`diff-${line.kind}`}>
                {line.kind === "added" ? "+ " : line.kind === "removed" ? "- " : "  "}
                {line.text}
              </div>
            ),
          )}
        </pre>
      ) : (
        <pre className="diff">{content}</pre>
      )}
    </div>
  );
}
