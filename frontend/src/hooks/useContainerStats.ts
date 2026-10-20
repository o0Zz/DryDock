import { useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { ContainerStats, StatsSample } from "../types";
import { usePoll } from "./usePoll";

const STATS_INTERVAL_MS = 5000;
// Same size as the backend ring buffer (stats_history_service.MAX_SAMPLES).
const MAX_SAMPLES = 60;

const NO_STATS: Record<string, ContainerStats> = {};

async function fetchStats(): Promise<Record<string, ContainerStats>> {
  const statsList = await api.containerStats();
  return Object.fromEntries(statsList.map((entry) => [entry.id, entry]));
}

/** Polls /api/containers/stats while mounted; each call takes ~1s server-side. */
export function useContainerStats(): Record<string, ContainerStats> {
  return usePoll(fetchStats, STATS_INTERVAL_MS) ?? NO_STATS;
}

/** Recent samples per container: the server's history at mount, then each poll of `stats`. */
export function useStatsHistory(
  stats: Record<string, ContainerStats>,
): Record<string, StatsSample[]> {
  const [history, setHistory] = useState<Record<string, StatsSample[]>>({});
  // The poll that was last appended, so a re-run of the effect does not add it twice.
  const appended = useRef<Record<string, ContainerStats> | null>(null);

  useEffect(() => {
    api
      .containerStatsHistory()
      .then(setHistory)
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    if (appended.current === stats || Object.keys(stats).length === 0) return;
    appended.current = stats;
    const at = new Date().toISOString();
    setHistory((current) => {
      // A container missing from one poll (stopping, or a failed read) keeps its history.
      const next = { ...current };
      for (const entry of Object.values(stats)) {
        const sample = { at, cpu_percent: entry.cpu_percent, memory_usage: entry.memory_usage };
        next[entry.id] = [...(current[entry.id] ?? []), sample].slice(-MAX_SAMPLES);
      }
      return next;
    });
  }, [stats]);

  return history;
}
