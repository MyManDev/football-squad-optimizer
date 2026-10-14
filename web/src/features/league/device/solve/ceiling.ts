/**
 * The device's clock rule, as the server's (`application/advice.py`,
 * `WINDOW_WALL_CEILING_SECONDS`): a ceiling is a safety stop, never a budget. A solve the
 * clock stops is not proved, and an unproved solve is refused (`DevicePlanRefused`),
 * never shown, as the server refuses a plan its ceiling cut short rather than publish one
 * machine's answer as though another would find it.
 */

import type { LpSolver } from "../lp/problem";

/**
 * The longest one request may spend solving, all its solves together: the primary, the
 * tie-break tiers, the hold and, with a chip or a rival strategy, their own. Far above
 * the work measured on the shipped tree: the slowest kind, a rival strategy, took 8.18 s at
 * worst on the owner's desktop (#1085; the plain plan 2.04 s, a chip 4.54 s, a Top 100
 * weight 5.78 s), so about 18 s on a processor 2.2 times slower. About 6.7 times that binds
 * only on a device far slower than any measured one, or on a solve that has stopped making
 * progress.
 */
export const DEVICE_SOLVE_CEILING_SECONDS = 120;

/** How long the page waits for the solver to load before the ceiling starts. */
export const DEVICE_LOAD_ALLOWANCE_SECONDS = 60;

/** How much longer than the ceiling the page waits for an answer before it stops the worker. */
export const DEVICE_REPLY_GRACE_SECONDS = 15;

/** The least time a solve is given, so a spent ceiling still asks once and is refused by status. */
const LEAST_SECONDS = 0.001;

/**
 * The solver, with every solve given what is left of the ceiling as HiGHS's `time_limit`.
 * The clock starts when this is made, after the solver has loaded.
 */
export function withinCeiling(
  solver: LpSolver,
  ceilingSeconds: number = DEVICE_SOLVE_CEILING_SECONDS,
  now: () => number = () => performance.now(),
): LpSolver {
  const started = now();
  return {
    solve(problem, options) {
      const left = ceilingSeconds - (now() - started) / 1000;
      return solver.solve(problem, { ...options, time_limit: Math.max(left, LEAST_SECONDS) });
    },
  };
}
