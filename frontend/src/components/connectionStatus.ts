import { msg } from "../i18n";

/** State of a streaming connection (logs over SSE, console over WebSocket). */
export type Status = "connecting" | "open" | "closed" | "error";

export const STATUS_LABELS: Record<Status, string> = {
  connecting: msg("connecting"),
  open: msg("open"),
  closed: msg("closed"),
  error: msg("error"),
};
