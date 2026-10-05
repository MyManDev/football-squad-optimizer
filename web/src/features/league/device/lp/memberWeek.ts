/**
 * One member's one-week problem: the fifteen to hold, the eleven to field, the captain,
 * under the game's quotas, the club limit, the bank and the transfer line. It restates
 * the one-week model the server builds (`squadopt/planning/optimizer.py`) over the numbers
 * the server publishes for exactly that purpose (`squadopt/application/device_plan.py`).
 *
 * The options are the ways the member path varies that model: a chip played this week, a
 * different charge per paid transfer (the price tag's anchor), a cap on this week's
 * transfers and a band on how many of a rival's players the fifteen may hold (a rival
 * strategy), and the tie-break tier that holds the primary value and ranks.
 */

import type { DeviceChip, DevicePlanDocument, DevicePlanEntry, DevicePlanPlayer } from "../types";
import { chipCoefficients, rebuilds } from "../strategies/chips";

/** Where a player's (squad, starter, captain) coefficients come from: the base points by default. */
export type CoefficientChoice = (player: DevicePlanPlayer) => [number, number, number];
import { row, term, type LpProblem, type LpRow, type LpTerm } from "./problem";

/** The three variable families, by the player's index in the document's order. */
export type VariablePrefix = "s" | "x" | "c";

export interface OverlapBand {
  /** The rival's players, as ids; ids the document does not carry cannot be held. */
  ids: readonly number[];
  minimum?: number;
  maximum?: number;
}

export interface TieBreak {
  primaryValue: number;
  prefix: VariablePrefix;
  /** The rank sums already settled by earlier tiers, as rows. */
  fixed: LpRow[];
}

export interface MemberWeekOptions {
  chip?: DeviceChip | null;
  /** The points the plan is chosen on, when not the base ones (a Top 100 weight). */
  choice?: CoefficientChoice;
  /** The cost per paid transfer on the objective scale; the rules' caution margin by default. */
  hitCostScaled?: number;
  /** At most this many transfers this week. */
  transferCap?: number;
  overlap?: OverlapBand;
  tieBreak?: TieBreak | null;
}

const variable = (prefix: VariablePrefix, index: number) => `${prefix}${index}`;

/** Sum of rank times variable; rank is the player's place in the document's order. */
export function rankSum(count: number, prefix: VariablePrefix): LpTerm[] {
  const terms: LpTerm[] = [];
  for (let index = 1; index < count; index += 1) terms.push(term(index, variable(prefix, index)));
  return terms;
}

/** The primary objective's terms: the week's points under the chip, less the paid transfers. */
export function primaryObjective(
  document: DevicePlanDocument,
  chip: DeviceChip | null,
  hitCostScaled: number,
  choice?: CoefficientChoice,
): LpTerm[] {
  const terms: LpTerm[] = [];
  document.players.forEach((player, index) => {
    const [squad, starter, captain] = choice ? choice(player) : chipCoefficients(player, chip);
    if (squad) terms.push(term(squad, variable("s", index)));
    if (starter) terms.push(term(starter, variable("x", index)));
    if (captain) terms.push(term(captain, variable("c", index)));
  });
  // A rebuild week pays no hits, so the paid transfers leave the objective.
  if (!rebuilds(chip)) terms.push(term(-hitCostScaled, "paid"));
  return terms;
}

export function memberWeekProblem(
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  options: MemberWeekOptions = {},
): LpProblem {
  const { players, rules } = document;
  const chip = options.chip ?? null;
  const hitCostScaled = options.hitCostScaled ?? rules.hit_cost_scaled;
  const heldSet = new Set(entry.held);
  const s = (i: number) => variable("s", i);
  const x = (i: number) => variable("x", i);
  const c = (i: number) => variable("c", i);
  const ones = (names: string[]) => names.map((name) => term(1, name));
  const indices = players.map((_, i) => i);

  const rows: LpRow[] = [];
  rows.push(row("squad", ones(indices.map(s)), "=", rules.squad_size));
  rows.push(row("xi", ones(indices.map(x)), "=", rules.starting_size));
  rows.push(row("cap", ones(indices.map(c)), "=", 1));
  for (const i of indices) {
    rows.push(row(`st${i}`, [term(1, x(i)), term(-1, s(i))], "<=", 0));
    rows.push(row(`ca${i}`, [term(1, c(i)), term(-1, x(i))], "<=", 0));
  }
  for (const position of Object.keys(rules.squad_position_limits)) {
    const members = indices.filter((i) => players[i]!.position === position);
    rows.push(
      row(`sq_${position}`, ones(members.map(s)), "=", rules.squad_position_limits[position]!),
    );
    rows.push(
      row(`lo_${position}`, ones(members.map(x)), ">=", rules.starting_position_min[position]!),
    );
    rows.push(
      row(`hi_${position}`, ones(members.map(x)), "<=", rules.starting_position_max[position]!),
    );
  }
  const clubs = new Map<string, number[]>();
  for (const i of indices) clubs.set(players[i]!.team, [...(clubs.get(players[i]!.team) ?? []), i]);
  [...clubs.values()].forEach((members, k) => {
    rows.push(row(`club${k}`, ones(members.map(s)), "<=", rules.max_players_per_team));
  });

  // A held player can only leave and anyone else can only arrive, so the squad variable
  // itself is the transfer: arriving is s = 1 off the squad, leaving is s = 0 on it.
  const arrivals = indices.filter((i) => !heldSet.has(players[i]!.id));
  const holders = indices.filter((i) => heldSet.has(players[i]!.id));
  rows.push(
    row(
      "paid",
      [term(1, "paid"), ...arrivals.map((i) => term(-1, s(i)))],
      ">=",
      -entry.free_transfers,
    ),
  );
  if (options.transferCap !== undefined) {
    rows.push(row("capped", ones(arrivals.map(s)), "<=", options.transferCap));
  }
  // bank + sum(sell * (1 - s)) over held - sum(buy * s) over arrivals >= 0
  const sell = (i: number) => entry.sell_tenths[String(players[i]!.id)] ?? players[i]!.buy_tenths;
  const proceeds = holders.reduce((total, i) => total + sell(i), 0);
  rows.push(
    row(
      "bank",
      [
        ...holders.map((i) => term(sell(i), s(i))),
        ...arrivals.map((i) => term(players[i]!.buy_tenths, s(i))),
      ],
      "<=",
      entry.bank_tenths + proceeds,
    ),
  );
  if (options.overlap) {
    const named = new Set(options.overlap.ids);
    const shared = ones(indices.filter((i) => named.has(players[i]!.id)).map(s));
    if (options.overlap.minimum !== undefined)
      rows.push(row("overlap_lo", shared, ">=", options.overlap.minimum));
    if (options.overlap.maximum !== undefined)
      rows.push(row("overlap_hi", shared, "<=", options.overlap.maximum));
  }

  const primary = primaryObjective(document, chip, hitCostScaled, options.choice);
  let sense: LpProblem["sense"] = "Maximize";
  let objective = primary;
  const tieBreak = options.tieBreak ?? null;
  if (tieBreak) {
    // The server's second solve: hold the primary value and minimise a rank sum, so equal
    // plans resolve the same way every time.
    rows.push(row("hold", primary, "=", tieBreak.primaryValue));
    sense = "Minimize";
    objective = rankSum(players.length, tieBreak.prefix);
    rows.push(...tieBreak.fixed);
  }

  return {
    sense,
    objective,
    rows,
    generals: [{ variable: "paid", lower: 0, upper: rules.squad_size }],
    binaries: indices.flatMap((i) => [s(i), x(i), c(i)]),
  };
}
