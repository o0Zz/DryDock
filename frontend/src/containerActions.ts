import { Play, RotateCw, Square, type LucideIcon } from "lucide-react";
import { lazy } from "react";
import type { ContainerAction } from "./types";

export const CONTAINER_ACTIONS: ContainerAction[] = ["start", "stop", "restart"];
export const CONTAINER_ACTION_ICONS: Record<ContainerAction, LucideIcon> = {
  start: Play,
  stop: Square,
  restart: RotateCw,
};

// xterm.js is heavy; only load it when a console is opened.
export const ContainerConsole = lazy(() => import("./components/ContainerConsole"));
