/**
 * A chip's effect on the week's objective and on what the week scores, from the planner's
 * own model (`squadopt/planning/optimizer.py`): a Bench Boost scores every squad member
 * in full, a Triple Captain counts the captain's coefficient once more, and a Wildcard or
 * a Free Hit lifts the hits and the cap and scores as any week does. The planner adds
 * each chip's term through a variable bounded above and maximised, so a negative
 * coefficient earns no term: a negative remainder stays on the eleven, a negative captain
 * is not tripled.
 */

import type { DeviceChip, DevicePlanAnswer, DevicePlanDocument, DevicePlanPlayer } from "../types";

/** (squad, starter, captain) under the chip, on the objective's integer scale. */
export function chipCoefficients(
  player: DevicePlanPlayer,
  chip: DeviceChip | null,
): [number, number, number] {
  const [squad, starter, captain] = player.coefficients;
  if (chip === "bboost") return [squad + Math.max(starter, 0), Math.min(starter, 0), captain];
  if (chip === "3xc") return [squad, starter, captain + Math.max(captain, 0)];
  return [squad, starter, captain];
}

/** A Wildcard or a Free Hit: unlimited transfers, none of them paid. */
export function rebuilds(chip: DeviceChip | null): boolean {
  return chip === "wildcard" || chip === "freehit";
}

/**
 * What a week scores on the document's own expected points: the eleven with the captain
 * doubled; tripled under a Triple Captain; every one of the fifteen under a Bench Boost.
 */
export function weekPoints(
  document: DevicePlanDocument,
  squad: number[],
  startingXi: number[],
  captain: number,
  chip: DeviceChip | null,
): number {
  const points = new Map(document.players.map((p) => [p.id, p.expected_points]));
  let total = 0;
  for (const id of chip === "bboost" ? squad : startingXi) total += points.get(id) ?? 0;
  return total + (chip === "3xc" ? 2 : 1) * (points.get(captain) ?? 0);
}

/**
 * A chip week beside the member's own no-chip plan: what the chip week scores minus its
 * hits, less the same for the plan without it. The server's `gain_vs_no_chip`, from the
 * two plans the device solved.
 */
export function gainVsNoChip(withChip: DevicePlanAnswer, without: DevicePlanAnswer): number {
  return (
    withChip.expected_own_points -
    withChip.transfer_hit_points -
    (without.expected_own_points - without.transfer_hit_points)
  );
}
