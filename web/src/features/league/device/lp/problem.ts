/**
 * A mixed-integer program as data, and its text for the solver.
 *
 * Every problem the device solves is built as an `LpProblem` and written once here, so
 * the LP syntax (one term a line, the sections, the bounds) lives in one place and the
 * modules that build problems only say what the constraints are.
 */

export interface LpTerm {
  coefficient: number;
  variable: string;
}

export type RowSense = "<=" | ">=" | "=";

export interface LpRow {
  name: string;
  terms: LpTerm[];
  sense: RowSense;
  rhs: number;
}

export interface LpBound {
  variable: string;
  lower: number;
  upper: number;
}

export interface LpProblem {
  sense: "Maximize" | "Minimize";
  objective: LpTerm[];
  rows: LpRow[];
  /** Integer variables with bounds; binaries need no bounds. */
  generals: LpBound[];
  binaries: string[];
}

/** The one-shot solver this model needs: HiGHS's legacy `solve` over LP text. */
export interface LpSolver {
  solve(
    problem: string,
    options?: Record<string, unknown>,
  ): {
    Status: string;
    ObjectiveValue: number;
    Columns: Record<string, { Primal: number }>;
  };
}

export type Solution = ReturnType<LpSolver["solve"]>;

/** No gap: the device proves its plan or says it did not. */
export const EXACT = { mip_rel_gap: 0, mip_abs_gap: 0, output_flag: false };

export function term(coefficient: number, variable: string): LpTerm {
  return { coefficient, variable };
}

/** The sum of the given terms, as a row. */
export function row(name: string, terms: LpTerm[], sense: RowSense, rhs: number): LpRow {
  return { name, terms, sense, rhs };
}

// One term a line: LP readers differ on how long a line may be, and none mind short ones.
function expression(terms: LpTerm[], fallback: string): string {
  const live = terms.filter((t) => t.coefficient !== 0);
  if (live.length === 0) return `0 ${fallback}`;
  return live
    .map((t, index) => {
      const sign = t.coefficient < 0 ? "-" : "+";
      const magnitude = Math.abs(t.coefficient);
      const lead = index === 0 ? (sign === "-" ? "- " : "") : `\n ${sign} `;
      return `${lead}${magnitude} ${t.variable}`;
    })
    .join("");
}

/** The problem in the LP file format the solver reads. */
export function lpText(problem: LpProblem): string {
  // An empty expression still needs a variable to stand on; any declared one will do.
  const anchor = problem.binaries[0] ?? problem.generals[0]?.variable ?? "x0";
  return [
    problem.sense,
    ` obj: ${expression(problem.objective, anchor)}`,
    "Subject To",
    ...problem.rows.map((r) => ` ${r.name}: ${expression(r.terms, anchor)} ${r.sense} ${r.rhs}`),
    ...(problem.generals.length
      ? [
          "Bounds",
          ...problem.generals.map((b) => ` ${b.lower} <= ${b.variable} <= ${b.upper}`),
          "General",
          ...problem.generals.map((b) => ` ${b.variable}`),
        ]
      : []),
    "Binary",
    ...problem.binaries.map((name) => ` ${name}`),
    "End",
  ].join("\n");
}

/** The ids whose variable with the given prefix the solution set to one, in id order. */
export function chosenIds(solution: Solution, ids: readonly number[], prefix: string): number[] {
  return ids
    .map((id, index) =>
      Math.round(solution.Columns[`${prefix}${index}`]?.Primal ?? 0) === 1 ? id : null,
    )
    .filter((id): id is number => id !== null)
    .sort((a, b) => a - b);
}
