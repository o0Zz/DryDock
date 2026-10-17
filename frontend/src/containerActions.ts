import { OctagonX, Pause, Play, RotateCw, Square, type LucideIcon } from "lucide-react";
import { lazy } from "react";
import type { ContainerAction } from "./types";

export const CONTAINER_ACTION_ICONS: Record<ContainerAction, LucideIcon> = {
  start: Play,
  stop: Square,
  restart: RotateCw,
  pause: Pause,
  unpause: Play,
  kill: OctagonX,
};

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
