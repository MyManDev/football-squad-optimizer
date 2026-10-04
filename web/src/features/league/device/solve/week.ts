/**
 * Solve one member's week: the primary problem, the server's three-tier tie-break, and
 * the hold problem, from the published document and the member's block. Every option
 * of the member path (a chip, a charge, a cap, a band) is passed through to the problem;
 * this module decides nothing about strategies, only how a problem is proved.
 */

import { lineupProblem } from "../lp/lineup";
import {
  memberWeekProblem,
  rankSum,
  type MemberWeekOptions,
  type VariablePrefix,
} from "../lp/memberWeek";
import { chosenIds, EXACT, lpText, row, type LpRow, type LpSolver } from "../lp/problem";
import { attributedMoves, orderedBench, viceCaptain } from "../publication/rows";
import { rebuilds, weekPoints } from "../strategies/chips";
import type { DevicePlanAnswer, DevicePlanDocument, DevicePlanEntry } from "../types";

export class DevicePlanRefused extends Error {
  readonly status: string;
  readonly stage: "plan" | "tie-break" | "hold";

  constructor(status: string, stage: "plan" | "tie-break" | "hold") {
    super(`The device solve did not prove a plan (${stage}: ${status}).`);
    this.name = "DevicePlanRefused";
    this.status = status;
    this.stage = stage;
  }
}

/** The document with its players in the order the planner sorts its own table into. */
export function inSolverOrder(published: DevicePlanDocument): DevicePlanDocument {
  // The planner sorts its table by id before it solves and ranks ties in that order;
  // the device does the same whatever order the document arrived in.
  return { ...published, players: [...published.players].sort((a, b) => a.id - b.id) };
}

/** What the primary and tie-break solves settled: the fifteen, the eleven, the captain. */
export interface WeekSolution {
  objectiveScaled: number;
  squad: number[];
  startingXi: number[];
  captain: number;
}

/**
 * The primary problem and the tie-break tiers. `null` when the constraints cannot be met
 * at all (a band the free transfers cannot reach); any other unproved outcome is refused.
 */
export function solveWeek(
  solver: LpSolver,
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  options: MemberWeekOptions = {},
): WeekSolution | null {
  const ids = document.players.map((p) => p.id);
  const first = solver.solve(lpText(memberWeekProblem(document, entry, options)), EXACT);
  if (first.Status === "Infeasible") return null;
  if (first.Status !== "Optimal") throw new DevicePlanRefused(first.Status, "plan");
  const primaryValue = Math.round(first.ObjectiveValue);

  // Captain rank decides first, then the starters' rank sum, then the squad's. One solve
  // per tier keeps every coefficient small instead of packing three tiers into one row.
  const fixed: LpRow[] = [];
  let last = first;
  for (const prefix of ["c", "x", "s"] as const satisfies readonly VariablePrefix[]) {
    const tier = solver.solve(
      lpText(
        memberWeekProblem(document, entry, {
          ...options,
          tieBreak: { primaryValue, prefix, fixed },
        }),
      ),
      EXACT,
    );
    if (tier.Status !== "Optimal") throw new DevicePlanRefused(tier.Status, "tie-break");
    fixed.push(
      row(`fix${fixed.length}`, rankSum(ids.length, prefix), "=", Math.round(tier.ObjectiveValue)),
    );
    last = tier;
  }
  return {
    objectiveScaled: primaryValue,
    squad: chosenIds(last, ids, "s"),
    startingXi: chosenIds(last, ids, "x"),
    captain: chosenIds(last, ids, "c")[0]!,
  };
}

/**
 * The value of fielding exactly a fifteen: its best eleven and captain on the same
 * objective, read on the week's basis. The basis every gain is on.
 */
export function squadValue(
  solver: LpSolver,
  document: DevicePlanDocument,
  options: Pick<MemberWeekOptions, "chip">,
): (squad: number[]) => number {
  const ids = document.players.map((p) => p.id);
  const chip = options.chip ?? null;
  return (squad) => {
    const fixed = solver.solve(lpText(lineupProblem(document, squad, chip)), EXACT);
    if (fixed.Status !== "Optimal") throw new DevicePlanRefused(fixed.Status, "hold");
    return weekPoints(
      document,
      squad,
      chosenIds(fixed, ids, "x"),
      chosenIds(fixed, ids, "c")[0]!,
      chip,
    );
  };
}

/** A proved week as the answer the page reads: transfers, hits, points, rows, bench. */
export function answerFrom(
  solver: LpSolver,
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  solution: WeekSolution,
  options: Pick<MemberWeekOptions, "chip">,
): Omit<DevicePlanAnswer, "seconds"> {
  const chip = options.chip ?? null;
  const valueOf = squadValue(solver, document, options);
  const heldSet = new Set(entry.held);
  const { squad, startingXi, captain } = solution;
  const transfersIn = squad.filter((id) => !heldSet.has(id));
  const transfersOut = entry.held.filter((id) => !squad.includes(id)).sort((a, b) => a - b);
  const paid = rebuilds(chip) ? 0 : Math.max(0, transfersIn.length - entry.free_transfers);
  const expectedOwnPoints = weekPoints(document, squad, startingXi, captain, chip);
  const holdPoints = valueOf(entry.held);
  const { moves, gain } = attributedMoves(
    document,
    entry.held,
    transfersOut,
    transfersIn,
    holdPoints,
    expectedOwnPoints,
    valueOf,
  );
  return {
    objective_scaled: solution.objectiveScaled,
    objective: solution.objectiveScaled / document.rules.expected_points_scale,
    squad,
    starting_xi: startingXi,
    captain,
    vice_captain: viceCaptain(document, startingXi, captain),
    bench: orderedBench(document, squad, startingXi),
    transfers_in: transfersIn,
    transfers_out: transfersOut,
    transfer_hit_points: paid * document.rules.hit_points_charged,
    expected_own_points: expectedOwnPoints,
    hold_points: holdPoints,
    moves,
    expected_gain_vs_hold: gain,
    chip,
  };
}

/**
 * The plain plan, or the plan with a chip played: the primary problem, the tie-break and
 * the hold problem. Throws `DevicePlanRefused` when any solve ends other than optimal: a
 * plan that was not proved is not shown.
 */
export function solvePlan(
  solver: LpSolver,
  published: DevicePlanDocument,
  entry: DevicePlanEntry,
  now: () => number = () => performance.now(),
  chip: DevicePlanAnswer["chip"] = null,
): DevicePlanAnswer {
  const started = now();
  const document = inSolverOrder(published);
  const solution = solveWeek(solver, document, entry, { chip });
  if (solution === null) throw new DevicePlanRefused("Infeasible", "plan");
  const answer = answerFrom(solver, document, entry, solution, { chip });
  return { ...answer, seconds: (now() - started) / 1000 };
}
