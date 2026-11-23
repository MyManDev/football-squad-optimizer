import type { LpProblem, LpRow, LpTerm, Solution } from "./lp/problem";
import type { DevicePlanDocument, DevicePlanEntry } from "./types";
import type { EntryAdvice } from "../types";

export interface DevicePriorityReference {
  squad: number[];
  startingXi: number[];
  captain: number;
  proved: boolean;
}

export type Values = Solution["Columns"];

export function shownPriorityReference(plan: EntryAdvice): DevicePriorityReference | undefined {
  if (
    !plan.starting_xi ||
    !plan.bench ||
    !plan.captain ||
    (plan.solver_status !== "FEASIBLE" && plan.solver_status !== "OPTIMAL")
  )
    return undefined;
  const startingXi = plan.starting_xi.map((p) => p.player_id).sort((a, b) => a - b);
  return {
    squad: [...startingXi, ...plan.bench.map((p) => p.player_id)].sort((a, b) => a - b),
    startingXi,
    captain: plan.captain.player_id,
    proved: plan.solver_status === "OPTIMAL",
  };
}

export const valueOf = (terms: readonly LpTerm[], values: Values) =>
  terms.reduce((sum, item) => sum + item.coefficient * (values[item.variable]?.Primal ?? 0), 0);

export const holds = (rows: readonly LpRow[], values: Values) =>
  rows.every((item) => {
    const value = valueOf(item.terms, values);
    return item.sense === "="
      ? value === item.rhs
      : item.sense === "<="
        ? value <= item.rhs
        : value >= item.rhs;
  });

/** An interrupted solver may have returned no incumbent, or only an LP relaxation. */
export function checkedColumns(problem: LpProblem, solution: Solution): Values | null {
  const values: Values = {};
  for (const { variable, lower, upper } of [
    ...problem.generals,
    ...problem.binaries.map((variable) => ({ variable, lower: 0, upper: 1 })),
  ]) {
    const raw = solution.Columns[variable]?.Primal;
    if (!Number.isFinite(raw)) return null;
    const n = Math.round(raw!);
    // HiGHS' default MIP feasibility tolerance. Check the resulting integer rows exactly.
    if (Math.abs(n - raw!) > 1e-6 || n < lower || n > upper) return null;
    values[variable] = { Primal: n };
  }
  return holds(problem.rows, values) ? values : null;
}

/** Reconstruct model columns exclusively from the physical main decisions. */
export function referenceValues(
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  reference: DevicePriorityReference,
): Values {
  const { squad, startingXi, captain } = reference;
  const ids = new Set(document.players.map((p) => p.id));
  if (
    typeof reference.proved !== "boolean" ||
    squad.length !== document.rules.squad_size ||
    new Set(squad).size !== squad.length ||
    startingXi.length !== document.rules.starting_size ||
    new Set(startingXi).size !== startingXi.length ||
    !squad.every((id) => ids.has(id)) ||
    !startingXi.every((id) => squad.includes(id)) ||
    !startingXi.includes(captain)
  )
    throw new Error("Invalid main witness.");
  const values: Values = {};
  document.players.forEach((p, i) => {
    values[`s${i}`] = { Primal: Number(squad.includes(p.id)) };
    values[`x${i}`] = { Primal: Number(startingXi.includes(p.id)) };
    values[`c${i}`] = { Primal: Number(captain === p.id) };
  });
  const incoming = squad.filter((id) => !entry.held.includes(id)).length;
  values.paid = { Primal: Math.max(0, incoming - entry.free_transfers) };
  values.moved = { Primal: Number(incoming > 0) };
  return values;
}
