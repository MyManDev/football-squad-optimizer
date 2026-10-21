/**
 * What the device is asked for, and which solve answers it. The worker and the tests
 * come through here; nothing else knows which module solves which selection.
 */

import { solveChipGains } from "./chipForecast/gains";
import type { LpSolver } from "./lp/problem";
import { DevicePlanRefused, solvePlan } from "./solve/week";
import { gainVsNoChip } from "./strategies/chips";
import { solveRival } from "./strategies/rival";
import { solveTop100 } from "./strategies/top100";
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
  /** A Top 100 weight the plan is chosen on; 0 or absent for the base points. */
  top100Weight?: number;
  /**
   * The held chips whose gain this week the chip timing reads: the plain plan, then each
   * chip solved once beside it. Empty or absent asks for none.
   */
  chipGains?: DeviceChip[];
}

/**
 * The plan asked for. With a chip: the chip week and, beside it, the member's own no-chip
 * plan the chip is measured against, exactly as the server measures `gain_vs_no_chip`.
 * With a rival strategy: the banded plan with its price and labels. The two combine with
 * nothing, as on the server. With chip gains: the plain plan, and each held chip's gain
 * against it, or null where its solve was refused; they too combine with nothing. The
 * plain plan is handed to `onPlan` as soon as it is solved, before any chip.
 */
export function solveRequest(
  solver: LpSolver,
  {
    document,
    entry,
    chip = null,
    strategy = null,
    top100Weight = 0,
    chipGains = [],
  }: Omit<DevicePlanRequest, "id">,
  now: () => number = () => performance.now(),
  onPlan?: (plan: DevicePlanAnswer) => void,
): DevicePlanAnswer {
  if (chipGains.length > 0) {
    if (chip !== null || strategy !== null || top100Weight !== 0) {
      throw new DevicePlanRefused("chip gains with a chip, a rival strategy or a weight", "plan");
    }
    return solveChipGains(solver, document, entry, chipGains, now, onPlan);
  }
  if (top100Weight !== 0) {
    // The device takes a weight on the one-week pure-points plan only. The server also
    // publishes a rival strategy at a weight; the device declines that by contract.
    if (chip !== null || strategy !== null) {
      throw new DevicePlanRefused("a weight with a chip or a rival strategy", "plan");
    }
    return solveTop100(solver, document, entry, top100Weight, now);
  }
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
