/**
 * The what-if mode's arithmetic (#1132): a fifteen the member puts together by hand, read
 * on the device solve's own terms. The rules are the rows of the member's one-week
 * problem (`memberWeekProblem`) evaluated at that fifteen, so a squad breaks exactly the
 * rows a plan could not break; its points are `squadValue`, the basis every device gain
 * is on. Nothing here decides a plan; it only reads one.
 */

import { memberWeekProblem } from "./lp/memberWeek";
import type { LpRow, LpSolver } from "./lp/problem";
import { DevicePlanRefused, inSolverOrder, squadValue } from "./solve/week";
import type { EntryAdvice } from "../types";
import type { DevicePlanDocument, DevicePlanEntry } from "./types";

/** A rule the fifteen breaks, as the row of the one-week problem that says it. */
export type WhatIfBreak =
  | { rule: "size"; count: number; size: number }
  | { rule: "position"; position: string; count: number; required: number }
  | { rule: "club"; team: string; count: number; limit: number }
  | { rule: "budget"; shortTenths: number };

export interface WhatIfAccount {
  /** What the bank holds after the fifteen's sales and purchases; below zero when over. */
  bankTenths: number;
  /** Players in the fifteen the member does not hold. */
  transfers: number;
  /** The paid transfers times what the game charges for one. */
  hitPoints: number;
  breaks: WhatIfBreak[];
}

/** The document in the order every row and every solve indexes its players by. */
export function whatIfDocument(published: DevicePlanDocument): DevicePlanDocument {
  return inSolverOrder(published);
}

/** A row's left side with each squad variable set by whether its player is in the fifteen. */
function evaluated(row: LpRow, document: DevicePlanDocument, chosen: ReadonlySet<number>) {
  let total = 0;
  for (const { coefficient, variable } of row.terms) {
    if (!variable.startsWith("s")) continue;
    const player = document.players[Number(variable.slice(1))];
    if (player && chosen.has(player.id)) total += coefficient;
  }
  return total;
}

/**
 * The fifteen's account under the member's block: the bank after it, its transfers and
 * hit, and every squad rule it breaks. `document` is in solver order (`whatIfDocument`).
 */
export function whatIfAccount(
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  squad: readonly number[],
): WhatIfAccount {
  const problem = memberWeekProblem(document, entry);
  const chosen = new Set(squad);
  const rows = new Map(problem.rows.map((row) => [row.name, row]));
  const breaks: WhatIfBreak[] = [];

  const size = rows.get("squad")!;
  const count = evaluated(size, document, chosen);
  if (count !== size.rhs) breaks.push({ rule: "size", count, size: size.rhs });
  for (const position of Object.keys(document.rules.squad_position_limits)) {
    const quota = rows.get(`sq_${position}`)!;
    const held = evaluated(quota, document, chosen);
    if (held !== quota.rhs)
      breaks.push({ rule: "position", position, count: held, required: quota.rhs });
  }
  for (const row of problem.rows) {
    if (!row.name.startsWith("club")) continue;
    const held = evaluated(row, document, chosen);
    if (held > row.rhs) {
      const first = document.players[Number(row.terms[0]!.variable.slice(1))]!;
      breaks.push({ rule: "club", team: first.team, count: held, limit: row.rhs });
    }
  }
  const bank = rows.get("bank")!;
  const bankTenths = bank.rhs - evaluated(bank, document, chosen);
  if (bankTenths < 0) breaks.push({ rule: "budget", shortTenths: -bankTenths });

  // paid >= arrivals - free: the row's squad terms are minus one per arrival.
  const paidRow = rows.get("paid")!;
  const transfers = 0 - evaluated(paidRow, document, chosen);
  const paid = Math.max(0, transfers + paidRow.rhs);
  return {
    bankTenths,
    transfers,
    hitPoints: paid * document.rules.hit_points_charged,
    breaks,
  };
}

/**
 * Each fifteen's points on the device's basis: its best eleven with the captain doubled,
 * as `squadValue` reads a fifteen for every gain the device prints. Null for a set no
 * eleven can be fielded from.
 */
export function whatIfValues(
  solver: LpSolver,
  document: DevicePlanDocument,
  squads: readonly (readonly number[])[],
): (number | null)[] {
  const valueOf = squadValue(solver, document, {});
  return squads.map((squad) => {
    try {
      return valueOf([...squad]);
    } catch (error) {
      if (error instanceof DevicePlanRefused) return null;
      throw error;
    }
  });
}

/**
 * The fifteen the mode starts from: a solved plan's eleven and bench, played without a
 * chip, so its points are on the basis the mode reads every fifteen on. Null otherwise.
 */
export function advisedFifteen(plan: EntryAdvice | null | undefined): number[] | null {
  if (
    !plan ||
    (plan.solver_status !== "OPTIMAL" && plan.solver_status !== "FEASIBLE") ||
    plan.starting_xi?.length !== 11 ||
    plan.bench?.length !== 4 ||
    (plan.chip ?? null) !== null
  )
    return null;
  const ids = [...plan.starting_xi, ...plan.bench].map((player) => player.player_id);
  return new Set(ids).size === 15 ? ids : null;
}
