/**
 * The lineup problem alone, for a fifteen taken as given: the eleven and the captain on
 * the server's objective, under the eleven's position bounds. The squad's own rules (the
 * club limit, the bank, the transfer line) do not bind a fifteen that is not being
 * chosen, exactly as the server's `best_eleven_points` reads a fifteen's worth. Under a
 * Bench Boost the fifteen's points are a constant and only the captain is chosen; the
 * eleven is then whichever the solver names, which is what it is for.
 */

import type { DeviceChip, DevicePlanDocument } from "../types";
import { chipCoefficients } from "../strategies/chips";
import { row, term, type LpProblem, type LpRow, type LpTerm } from "./problem";

export function lineupProblem(
  document: DevicePlanDocument,
  squad: readonly number[],
  chip: DeviceChip | null = null,
): LpProblem {
  const { players, rules } = document;
  const inSquad = new Set(squad);
  const x = (i: number) => `x${i}`;
  const c = (i: number) => `c${i}`;
  const chosen = players.map((p, i) => (inSquad.has(p.id) ? i : -1)).filter((i) => i >= 0);
  const ones = (names: string[]) => names.map((name) => term(1, name));
  const objective: LpTerm[] = [];
  for (const i of chosen) {
    const [, starter, captain] = chipCoefficients(players[i]!, chip);
    if (starter) objective.push(term(starter, x(i)));
    if (captain) objective.push(term(captain, c(i)));
  }
  const rows: LpRow[] = [];
  rows.push(row("xi", ones(chosen.map(x)), "=", rules.starting_size));
  rows.push(row("cap", ones(chosen.map(c)), "=", 1));
  for (const i of chosen) rows.push(row(`ca${i}`, [term(1, c(i)), term(-1, x(i))], "<=", 0));
  for (const position of Object.keys(rules.squad_position_limits)) {
    const members = chosen.filter((i) => players[i]!.position === position);
    rows.push(
      row(`lo_${position}`, ones(members.map(x)), ">=", rules.starting_position_min[position]!),
    );
    rows.push(
      row(`hi_${position}`, ones(members.map(x)), "<=", rules.starting_position_max[position]!),
    );
  }
  return {
    sense: "Maximize",
    objective,
    rows,
    generals: [],
    binaries: chosen.flatMap((i) => [x(i), c(i)]),
  };
}
