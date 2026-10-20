import { api } from "../api";
import type { HostUsage } from "../types";
import { usePoll } from "./usePoll";

const HOST_INTERVAL_MS = 5000;

/** Polls /api/dashboard/host while mounted. */
export function useHostUsage(): HostUsage | null {
  return usePoll(api.hostUsage, HOST_INTERVAL_MS);
}
