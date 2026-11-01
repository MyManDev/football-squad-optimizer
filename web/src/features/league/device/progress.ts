/** What the progress card reads of a device run: whether it is counting, and how far. */

import type { DevicePlanPhase, DeviceProgress } from "./useDevicePlan";

/** The run's progress while it is counting; null once nothing is. */
export function countingProgress(state: DevicePlanPhase): DeviceProgress | null {
  if (state.phase !== "loading" && state.phase !== "solving" && state.phase !== "done") {
    return null;
  }
  return state.progress ?? null;
}

/** The share of the run done, from 0 to 1; nothing is done before the inputs say how much. */
export function progressShare(progress: DeviceProgress): number {
  return progress.total === null || progress.total === 0
    ? 0
    : Math.min(1, progress.done / progress.total);
}
