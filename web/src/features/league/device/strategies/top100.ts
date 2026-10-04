/**
 * The Top 100 influence on the device: `advice.advise_with_top100` restated.
 *
 * The setting moves the points a plan is chosen on and nothing else. The document carries
 * each player's weighted points on the objective's integer scale, scaled by the server;
 * the device derives the bench coefficient from that integer by the server's rounding
 * rule (round half up of a tenth) and chooses the fifteen, the eleven and the captain on
 * those integers. Everything stated is the base model's: the points, the rows, the gain
 * against holding, all read on the base projection with the eleven the weighted choice
 * fields. The price is what choosing on the weight gives up in the base model against the
 * member's own pure-points plan, both net of hits, floored at zero.
 */

import type { LpSolver } from "../lp/problem";
import { answerFrom, DevicePlanRefused, inSolverOrder, solveWeek } from "../solve/week";
import type {
  DevicePlanAnswer,
  DevicePlanDocument,
  DevicePlanEntry,
  DevicePlanPlayer,
  DeviceTop100Fields,
} from "../types";

/** The server's bench coefficient from a scaled integer: round half up of a tenth. */
export function benchCoefficient(scaled: number): number {
  return scaled >= 0 ? Math.floor((scaled + 5) / 10) : -Math.floor((-scaled + 5) / 10);
}

/** (squad, starter, captain) on the weighted points, from the document's integers. */
export function top100Coefficients(
  player: DevicePlanPlayer,
  weight: number,
): [number, number, number] {
  const scaled = player.top100_scaled?.[String(weight)];
  if (scaled === undefined) {
    throw new DevicePlanRefused(`no weighted points at ${weight}`, "plan");
  }
  const bench = benchCoefficient(scaled);
  return [bench, scaled - bench, scaled];
}

/** Whether the document carries the weight the request asks for. */
export function offersWeight(document: DevicePlanDocument, weight: number): boolean {
  return document.rules.top100?.weights.includes(weight) === true;
}

export function solveTop100(
  solver: LpSolver,
  published: DevicePlanDocument,
  entry: DevicePlanEntry,
  weight: number,
  now: () => number = () => performance.now(),
): DevicePlanAnswer {
  const started = now();
  const document = inSolverOrder(published);
  if (!offersWeight(document, weight)) throw new DevicePlanRefused("weight not offered", "plan");
  const choice = (player: DevicePlanPlayer) => top100Coefficients(player, weight);

  // The member's own pure-points plan, the price's anchor, on base points.
  const control = solveWeek(solver, document, entry, {});
  if (control === null) throw new DevicePlanRefused("Infeasible", "plan");
  const controlAnswer = answerFrom(solver, document, entry, control, {});
  // The plan chosen on the weighted points, stated on the base ones.
  const preferred = solveWeek(solver, document, entry, { choice });
  if (preferred === null) throw new DevicePlanRefused("Infeasible", "plan");
  const answer = answerFrom(solver, document, entry, preferred, { choice });

  const controlNet = controlAnswer.expected_own_points - controlAnswer.transfer_hit_points;
  const selectedNet = answer.expected_own_points - answer.transfer_hit_points;
  const cost = Math.max(controlNet, selectedNet) - selectedNet;
  const same = (a: readonly number[], b: readonly number[]) =>
    a.length === b.length && a.every((value, index) => value === b[index]);
  const changed =
    !same(controlAnswer.transfers_in, answer.transfers_in) ||
    !same(controlAnswer.transfers_out, answer.transfers_out) ||
    !same(controlAnswer.starting_xi, answer.starting_xi) ||
    controlAnswer.captain !== answer.captain;
  // A move the pure-points plan also makes is a points gain; one only the weighted plan
  // makes is the setting's; and a row the base model scores below zero is the setting's
  // whatever else it is.
  const controlIn = new Set(controlAnswer.transfers_in);
  const controlOut = new Set(controlAnswer.transfers_out);
  const reasons = answer.moves.map((move) => {
    const shared =
      move.out !== null && move.in !== null && controlOut.has(move.out) && controlIn.has(move.in);
    const negative = move.gain !== null && move.gain < -1e-9;
    return shared && !negative ? "points_gain" : "top100_preference";
  });
  const fields: DeviceTop100Fields = {
    weight,
    changed,
    expected_points_cost: cost,
    expected_points_cost_ceiling: cost,
    reasons,
  };
  return { ...answer, top100: fields, seconds: (now() - started) / 1000 };
}
