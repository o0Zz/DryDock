import { OctagonX, Pause, Play, RotateCw, Square, type LucideIcon } from "lucide-react";
import { lazy } from "react";
import { msg } from "./i18n";
import type { ContainerAction } from "./types";

export const CONTAINER_ACTION_ICONS: Record<ContainerAction, LucideIcon> = {
  start: Play,
  stop: Square,
  restart: RotateCw,
  pause: Pause,
  unpause: Play,
  kill: OctagonX,
};

/** Button text per action; the action itself is the API value. */
export const CONTAINER_ACTION_LABELS: Record<ContainerAction, string> = {
  start: msg("start"),
  stop: msg("stop"),
  restart: msg("restart"),
  pause: msg("pause"),
  unpause: msg("unpause"),
  kill: msg("kill"),
};

// Docker's container states as shown in badges; the raw state stays the CSS class.
const CONTAINER_STATE_LABELS: Record<string, string> = {
  created: msg("created"),
  running: msg("running"),
  paused: msg("paused"),
  restarting: msg("restarting"),
  removing: msg("removing"),
  exited: msg("exited"),
  dead: msg("dead"),
};

/** The text to translate for a state; an unknown state is shown as Docker reports it. */
export function containerStateLabel(state: string): string {
  return CONTAINER_STATE_LABELS[state] ?? state;
}

/** The actions that make sense for a container in this state. */
export function containerActionsFor(state: string): ContainerAction[] {
  switch (state) {
    case "running":
      return ["stop", "restart", "pause", "kill"];
    case "paused":
      return ["unpause", "kill"];
    case "restarting":
      return ["stop", "kill"];
    default:
      return ["start"];
  }
}

// xterm.js is heavy; only load it when a console is opened.
export const ContainerConsole = lazy(() => import("./components/ContainerConsole"));
