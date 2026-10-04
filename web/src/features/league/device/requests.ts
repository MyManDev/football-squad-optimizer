/**
 * What the device is asked for, and which solve answers it. The worker and the tests
 * come through here; nothing else knows which module solves which selection.
 */

import type { LpSolver } from "./lp/problem";
import { DevicePlanRefused, solvePlan } from "./solve/week";
import { gainVsNoChip } from "./strategies/chips";
import { solveRival } from "./strategies/rival";
import type {
  DeviceChip,
  DevicePlanAnswer,
  DevicePlanDocument,
  DevicePlanEntry,
  DeviceRival,
  RivalStrategy,
} from "./types";

export interface DevicePlanRequest {
  id: number;
  document: DevicePlanDocument;
  entry: DevicePlanEntry;
  /** A chip to play this week, or null for the plain plan. */
  chip?: DeviceChip | null;
  /** A rival strategy against the named rival; null for the pure-points plan. */
  strategy?: { name: RivalStrategy; rival: DeviceRival } | null;
}

/**
 * The plan asked for. With a chip: the chip week and, beside it, the member's own no-chip
 * plan the chip is measured against, exactly as the server measures `gain_vs_no_chip`.
 * With a rival strategy: the banded plan with its price and labels. The two combine with
 * nothing, as on the server.
 */
export function solveRequest(
  solver: LpSolver,
  { document, entry, chip = null, strategy = null }: Omit<DevicePlanRequest, "id">,
  now: () => number = () => performance.now(),
): DevicePlanAnswer {
  if (strategy !== null) {
    if (chip !== null) throw new DevicePlanRefused("a chip with a rival strategy", "plan");
    return solveRival(solver, document, entry, strategy.rival, strategy.name, now);
  }
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
