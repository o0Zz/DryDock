import type { ContainerPort } from "./types";

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** unitIndex).toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
}

/** Local date and time of an API timestamp, or `fallback` when there is none. */
export function formatDate(value: string | null | undefined, fallback = "—"): string {
  return value ? new Date(value).toLocaleString() : fallback;
}

/** Published ports as `8080→80/tcp, …`, or "—" when nothing is published. */
export function formatPorts(ports: ContainerPort[]): string {
  return (
    ports
      .filter((port) => port.public_port)
      .map((port) => `${port.public_port}→${port.private_port}/${port.protocol}`)
      .join(", ") || "—"
  );
}

/** Rough length of a span of seconds, e.g. `3d 4h` or `12m`. */
export function formatDuration(seconds: number): string {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}
