import type { ContainerPort } from "./types";

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** i).toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

/** Local date and time of an API timestamp, or `fallback` when there is none. */
export function formatDate(value: string | null | undefined, fallback = "—"): string {
  return value ? new Date(value).toLocaleString() : fallback;
}

/** Published ports as `8080→80/tcp, …`, or "—" when nothing is published. */
export function formatPorts(ports: ContainerPort[]): string {
  return (
    ports
      .filter((p) => p.public_port)
      .map((p) => `${p.public_port}→${p.private_port}/${p.protocol}`)
      .join(", ") || "—"
  );
}
