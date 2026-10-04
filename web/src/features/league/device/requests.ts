/**
 * What the device is asked for, and which solve answers it. The worker and the tests
 * come through here; nothing else knows which module solves which selection.
 */

import type { LpSolver } from "./lp/problem";
import { solvePlan } from "./solve/week";
import { gainVsNoChip } from "./strategies/chips";
import type { DeviceChip, DevicePlanAnswer, DevicePlanDocument, DevicePlanEntry } from "./types";

export interface DevicePlanRequest {
  id: number;
  document: DevicePlanDocument;
  entry: DevicePlanEntry;
  /** A chip to play this week, or null for the plain plan. */
  chip?: DeviceChip | null;
}

/**
 * The plan asked for: with a chip, the chip week and, beside it, the member's own no-chip
 * plan the chip is measured against, exactly as the server measures `gain_vs_no_chip`.
 */
export function solveRequest(
  solver: LpSolver,
  { document, entry, chip = null }: Omit<DevicePlanRequest, "id">,
  now: () => number = () => performance.now(),
): DevicePlanAnswer {
  if (chip === null) return solvePlan(solver, document, entry, now);
  const started = now();
  const without = solvePlan(solver, document, entry, now);
  const answer = solvePlan(solver, document, entry, now, chip);
  return {
    ...answer,
    gain_vs_no_chip: gainVsNoChip(answer, without),
    seconds: (now() - started) / 1000,
  };
}
