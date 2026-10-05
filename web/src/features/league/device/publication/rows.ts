/**
 * How a solved week is written as the advice document: the server's own publication
 * rules, restated. The swaps paired by position in id order, each row's gain as the basis
 * moves when it is applied after the rows above it, the vice-captain as the eleven's
 * next-highest, the bench in the order the game walks it.
 */

import type { DevicePlanDocument, DevicePlanMove } from "../types";

/**
 * The server's pairing: each outgoing player with an incoming player of the same
 * position, both lists in id order; whatever is left over is paired in id order at the
 * end rather than dropped.
 */
export function pairedByPosition(
  document: DevicePlanDocument,
  outs: readonly number[],
  ins: readonly number[],
): Array<[number | null, number | null]> {
  const position = new Map(document.players.map((p) => [p.id, p.position]));
  const waiting = new Map<string, number[]>();
  const spareIns: number[] = [];
  for (const arriving of ins) {
    const where = position.get(arriving);
    if (where === undefined) spareIns.push(arriving);
    else waiting.set(where, [...(waiting.get(where) ?? []), arriving]);
  }
  const pairs: Array<[number | null, number | null]> = [];
  const spareOuts: number[] = [];
  for (const leaving of outs) {
    const where = position.get(leaving);
    const queue = where === undefined ? undefined : waiting.get(where);
    if (queue && queue.length) pairs.push([leaving, queue.shift()!]);
    else spareOuts.push(leaving);
  }
  const leftoverIns = [...[...waiting.values()].flat(), ...spareIns].sort((a, b) => a - b);
  for (let index = 0; index < Math.max(spareOuts.length, leftoverIns.length); index += 1) {
    pairs.push([spareOuts[index] ?? null, leftoverIns[index] ?? null]);
  }
  return pairs;
}

/**
 * Each swap's share of the gain: the rows are applied to the held fifteen in order and
 * the basis re-read after each. Null on every row, and no total, when the chain does
 * not end at the eleven the plan fields.
 */
export function attributedMoves(
  document: DevicePlanDocument,
  held: readonly number[],
  outs: readonly number[],
  ins: readonly number[],
  holdPoints: number,
  expectedOwnPoints: number,
  valueOf: (squad: number[]) => number,
): { moves: DevicePlanMove[]; gain: number | null } {
  const pairs = pairedByPosition(document, outs, ins);
  const squad = [...held];
  const gains: number[] = [];
  let previous = holdPoints;
  let walkable = true;
  for (const [leaving, arriving] of pairs) {
    if (!walkable) break;
    if (
      leaving === null ||
      arriving === null ||
      !squad.includes(leaving) ||
      squad.includes(arriving)
    ) {
      walkable = false;
      break;
    }
    squad[squad.indexOf(leaving)] = arriving;
    const value = valueOf(squad);
    gains.push(value - previous);
    previous = value;
  }
  if (!walkable || Math.abs(previous - expectedOwnPoints) > 1e-6) {
    return {
      moves: pairs.map(([out, arriving]) => ({ out, in: arriving, gain: null })),
      gain: null,
    };
  }
  return {
    moves: pairs.map(([out, arriving], index) => ({
      out,
      in: arriving,
      gain: gains[index] ?? null,
    })),
    gain: gains.reduce((total, value) => total + value, 0),
  };
}

/** The server's completion rule: the eleven's next-highest points, the lower id on a tie. */
export function viceCaptain(
  document: DevicePlanDocument,
  startingXi: readonly number[],
  captain: number,
): number {
  const points = new Map(document.players.map((p) => [p.id, p.expected_points]));
  const eligible = startingXi.filter((id) => id !== captain);
  eligible.sort((a, b) => (points.get(b) ?? 0) - (points.get(a) ?? 0) || a - b);
  return eligible[0]!;
}

/**
 * The bench in the order the game walks it: the goalkeeper first, then outfield by
 * descending expected points, the document's order on a tie. The server's shared bench
 * rule orders by points per appearance chance where every row carries one and falls
 * back to points otherwise; the one-week member path's table carries no chance, so the
 * fallback is what the server publishes for this plan.
 */
export function orderedBench(
  document: DevicePlanDocument,
  squad: readonly number[],
  startingXi: readonly number[],
): number[] {
  const starters = new Set(startingXi);
  const rows = document.players.filter((p) => squad.includes(p.id) && !starters.has(p.id));
  const keepers = rows.filter((p) => p.position === "GK").map((p) => p.id);
  const outfield = rows
    .map((p, order) => ({ p, order }))
    .filter(({ p }) => p.position !== "GK")
    .sort((a, b) => b.p.expected_points - a.p.expected_points || a.order - b.order)
    .map(({ p }) => p.id);
  return [...keepers, ...outfield];
}
