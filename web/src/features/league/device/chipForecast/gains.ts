/**
 * This week's gain of each held chip, as the chip timing reads it: the member's plain
 * plan once, then each chip's week solved once and measured against that same plan, so
 * the request makes 1 + n solves rather than a chip request's two for each chip. A chip
 * whose solve is refused, the device's ceiling included, has an unknown gain: null, never
 * zero, so the rule reads it as unknown this week and the plan itself still stands.
 * The plain plan, with its own solving time, is handed to `onPlan` before the first chip
 * is solved, so the page can show it at the plain plan's pace, and `onChip` hears each chip
 * tried, refused ones included, so the page can count them.
 */

import type { LpSolver } from "../lp/problem";
import { DevicePlanRefused, solvePlan } from "../solve/week";
import { gainVsNoChip } from "../strategies/chips";
import {
  DEVICE_CHIPS,
  type DeviceChip,
  type DevicePlanAnswer,
  type DevicePlanDocument,
  type DevicePlanEntry,
} from "../types";

export function solveChipGains(
  solver: LpSolver,
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  chips: readonly DeviceChip[],
  now: () => number = () => performance.now(),
  onPlan?: (plan: DevicePlanAnswer) => void,
  onChip?: (done: number, total: number) => void,
): DevicePlanAnswer {
  const started = now();
  const plain = solvePlan(solver, document, entry, now);
  onPlan?.(plain);
  const gains: Partial<Record<DeviceChip, number | null>> = {};
  // Each chip once, in the game's order, whatever order or repeats the request named.
  const held = DEVICE_CHIPS.filter((name) => chips.includes(name));
  for (const [index, chip] of held.entries()) {
    try {
      gains[chip] = gainVsNoChip(solvePlan(solver, document, entry, now, chip), plain);
    } catch (error) {
      if (!(error instanceof DevicePlanRefused)) throw error;
      gains[chip] = null;
    }
    onChip?.(index + 1, held.length);
  }
  return { ...plain, chip_gains: gains, seconds: (now() - started) / 1000 };
}
