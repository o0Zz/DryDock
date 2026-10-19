import { translate } from "./i18n";
import type { ContainerPort } from "./types";

export function formatBytes(bytes: number): string {
  // French writes octets: o, Ko, Mo.
  const units = [
    translate("B"),
    translate("KB"),
    translate("MB"),
    translate("GB"),
    translate("TB"),
  ];
  if (!bytes) return `0 ${units[0]}`;
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** unitIndex).toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

/** Local date and time of an API timestamp, or `fallback` when there is none. */
export function formatDate(value: string | null | undefined, fallback = "—"): string {
  return value ? new Date(value).toLocaleString() : fallback;
}

/** Published ports as `8080→80/tcp, …`, or "—" when nothing is published. */
export function formatPorts(ports: ContainerPort[]): string {
  // Docker lists one binding per host IP (0.0.0.0 and ::), so the same mapping comes twice.
  const mappings = ports
    .filter((port) => port.public_port)
    .map((port) => `${port.public_port}→${port.private_port}/${port.protocol}`);
  return [...new Set(mappings)].join(", ") || "—";
}

/** Seconds from an API timestamp to now, or null when there is none. */
export function secondsSince(value: string | null | undefined): number | null {
  return value ? Math.max(0, (Date.now() - Date.parse(value)) / 1000) : null;
}

/** Rough length of a span of seconds, e.g. `3d 4h` or `12m`. */
export function formatDuration(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return translate("{days}d {hours}h", { days, hours });
  if (hours > 0) return translate("{hours}h {minutes}m", { hours, minutes });
  return translate("{minutes}m", { minutes });
}
