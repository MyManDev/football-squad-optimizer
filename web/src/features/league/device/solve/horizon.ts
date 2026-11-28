/** A proved plain H3/H5 plan and its weekly squads, moves and resources. */
import {
  horizonInputs,
  horizonProblem,
  horizonRanks,
  horizonVariable,
  type HorizonPoolMode,
} from "../lp/horizon";
import { chosenIds, EXACT, lpText, row, type LpSolver, type Solution } from "../lp/problem";
import { checkedColumns, valueOf } from "../priorityWitness";
import { orderedBench, viceCaptain } from "../publication/rows";
import type { DevicePlanAnswer, DevicePlanDocument, DevicePlanEntry } from "../types";
import { answerFrom, DevicePlanRefused, inSolverOrder } from "./week";

export interface DeviceHorizonWeek {
  gameweek: number;
  squad: number[];
  starting_xi: number[];
  captain: number;
  vice_captain: number;
  bench: number[];
  transfers_in: number[];
  transfers_out: number[];
  bank_after_tenths: number;
  free_transfers_before: number;
  free_transfers_after: number;
  transfer_hit_points: number;
  expected_points: number;
}

export interface DeviceHorizonAnswer extends DevicePlanAnswer {
  window: 3 | 5;
  plan_weeks: DeviceHorizonWeek[];
}

function proved(
  solver: LpSolver,
  problem: ReturnType<typeof horizonProblem>,
  stage: "plan" | "tie-break",
): Solution {
  const solution = solver.solve(lpText(problem), EXACT);
  if (solution.Status !== "Optimal") throw new DevicePlanRefused(solution.Status, stage);
  const columns = checkedColumns(problem, solution);
  if (columns === null) throw new DevicePlanRefused("invalid integer horizon witness", stage);
  return { ...solution, Columns: columns };
}

export function solveHorizon(
  solver: LpSolver,
  published: DevicePlanDocument,
  entry: DevicePlanEntry,
  window: 3 | 5,
  now: () => number = () => performance.now(),
  poolMode: HorizonPoolMode = "reduced",
): DeviceHorizonAnswer {
  const started = now();
  const document = inSolverOrder(published);
  const inputs = horizonInputs(document, window);
  // Only the horizon LP is reduced. Reporting, hold value and attributed moves
  // continue to use the complete solver-order document below.
  const problem = horizonProblem(document, entry, window, poolMode);
  let solution = proved(solver, problem, "plan");
  const primary = valueOf(problem.objective, solution.Columns);
  const fixed = [row("primary_optimum", problem.objective, "=", primary)];
  for (const family of ["c", "x", "s"] as const) {
    const objective = horizonRanks(document.players.length, window, family, problem.playerIndices);
    solution = proved(
      solver,
      { ...problem, sense: "Minimize", objective, rows: [...problem.rows, ...fixed] },
      "tie-break",
    );
    fixed.push(row(`rank_${family}`, objective, "=", valueOf(objective, solution.Columns)));
  }
  const ids = document.players.map((player) => player.id);
  const n = (family: string, w: number) => solution.Columns[horizonVariable(family, w)]!.Primal;
  let objective = 0;
  const weeks: DeviceHorizonWeek[] = inputs.weeks.slice(0, window).map((week, w) => {
    const points = new Map(week.players.map((player) => [player.id, player]));
    const onWeek: DevicePlanDocument = {
      ...document,
      gameweek: week.gameweek,
      players: document.players.map((player) => ({ ...player, ...points.get(player.id)! })),
    };
    const chosen = (family: string) => chosenIds(solution, ids, `${horizonVariable(family, w)}_`);
    const squad = chosen("s"),
      startingXi = chosen("x"),
      captain = chosen("c")[0]!;
    const expectedPoints =
      startingXi.reduce((total, id) => total + points.get(id)!.expected_points, 0) +
      points.get(captain)!.expected_points;
    const bench = orderedBench(onWeek, squad, startingXi);
    const benchPoints = bench.reduce((total, id) => total + points.get(id)!.expected_points, 0);
    objective +=
      inputs.rules.horizon_discount_factor ** w *
      (expectedPoints +
        inputs.rules.bench_weight * benchPoints -
        (n("p", w) * document.rules.hit_cost_scaled) / document.rules.expected_points_scale);
    return {
      gameweek: week.gameweek,
      squad,
      starting_xi: startingXi,
      captain,
      vice_captain: viceCaptain(onWeek, startingXi, captain),
      bench,
      transfers_in: chosen("i"),
      transfers_out: chosen("o"),
      bank_after_tenths: n("b", w),
      free_transfers_before: n("f", w),
      free_transfers_after: n("n", w),
      transfer_hit_points: n("p", w) * document.rules.hit_points_charged,
      expected_points: expectedPoints,
    };
  });
  const first = weeks[0]!;
  const answer = answerFrom(
    solver,
    document,
    entry,
    {
      objectiveScaled: primary,
      squad: first.squad,
      startingXi: first.starting_xi,
      captain: first.captain,
    },
    {},
  );
  return {
    ...answer,
    objective,
    objective_scaled: primary,
    window,
    plan_weeks: weeks,
    bank_after_tenths: first.bank_after_tenths,
    free_transfers_before: first.free_transfers_before,
    free_transfers_after: first.free_transfers_after,
    seconds: (now() - started) / 1000,
  };
}
