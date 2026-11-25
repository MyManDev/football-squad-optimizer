/** Canonical count layers and one binding concession floor in the device model. */
import { checkedPreferences, preferencesKey } from "../advice/decisionPreferences";
import {
  priorityRuleIdentity,
  type PriorityProgram,
  type PriorityResult,
} from "../advice/preferenceBundle";
import { memberWeekProblem } from "./lp/memberWeek";
import {
  chosenIds,
  EXACT,
  lpText,
  row,
  term,
  type LpRow,
  type LpSolver,
  type LpTerm,
  type Solution,
} from "./lp/problem";
import { hardPreferenceRows, oneWeekPreferences } from "./preferences";
import { checkedColumns, holds, referenceValues, valueOf, type Values } from "./priorityWitness";
import { orderedBench, viceCaptain } from "./publication/rows";
import { DevicePlanRefused, inSolverOrder } from "./solve/week";
import { rebuilds, weekPoints } from "./strategies/chips";
import type { DevicePlanAnswer, DevicePlanDocument, DevicePlanEntry } from "./types";

/** The witness already settled by a count layer; no new search is used to publish it. */
function answerFor(
  document: DevicePlanDocument,
  entry: DevicePlanEntry,
  baseline: DevicePlanAnswer,
  values: Values,
  points: readonly LpTerm[],
  metadata: PriorityResult,
  seconds: number,
): DevicePlanAnswer {
  const ids = document.players.map((player) => player.id);
  const solution: Solution = {
    Status: "Optimal",
    ObjectiveValue: valueOf(points, values),
    Columns: values,
  };
  const squad = chosenIds(solution, ids, "s"),
    startingXi = chosenIds(solution, ids, "x");
  const captain = chosenIds(solution, ids, "c")[0];
  if (
    squad.length !== document.rules.squad_size ||
    startingXi.length !== document.rules.starting_size ||
    captain === undefined
  )
    throw new Error("The priority witness is incomplete.");
  const held = new Set(entry.held),
    selected = new Set(squad);
  const incoming = squad.filter((id) => !held.has(id)),
    outgoing = entry.held.filter((id) => !selected.has(id));
  const moves: DevicePlanAnswer["moves"] = [];
  for (const position of Object.keys(document.rules.squad_position_limits)) {
    const matching = (set: number[]) =>
      set
        .filter((id) => document.players.some((p) => p.id === id && p.position === position))
        .sort((a, b) => a - b);
    const ins = matching(incoming),
      outs = matching(outgoing);
    if (ins.length !== outs.length) throw new Error("Priority transfer positions do not balance.");
    ins.forEach((id, i) => moves.push({ in: id, out: outs[i]!, gain: null }));
  }
  const paid = rebuilds(baseline.chip) ? 0 : Math.max(0, incoming.length - entry.free_transfers);
  const own = weekPoints(document, squad, startingXi, captain, baseline.chip);
  const sell = outgoing.reduce(
    (sum, id) =>
      sum +
      (entry.sell_tenths[String(id)] ?? document.players.find((p) => p.id === id)!.buy_tenths),
    0,
  );
  const buy = incoming.reduce(
    (sum, id) => sum + document.players.find((p) => p.id === id)!.buy_tenths,
    0,
  );
  const objective = Math.round(valueOf(points, values));
  return {
    ...baseline,
    restricted: true,
    priority_preferences: metadata,
    objective_scaled: objective,
    objective: objective / document.rules.expected_points_scale,
    squad,
    starting_xi: startingXi,
    captain,
    vice_captain: viceCaptain(document, startingXi, captain),
    bench: orderedBench(document, squad, startingXi),
    transfers_in: incoming,
    transfers_out: outgoing,
    transfer_hit_points: paid * document.rules.hit_points_charged,
    expected_own_points: own,
    expected_gain_vs_hold: own - baseline.hold_points,
    moves,
    bank_after_tenths:
      baseline.chip === "freehit" ? entry.bank_tenths : entry.bank_tenths + sell - buy,
    free_transfers_before: entry.free_transfers,
    free_transfers_after: rebuilds(baseline.chip)
      ? entry.free_transfers
      : Math.min(
          document.rules.max_free_transfers,
          Math.max(0, entry.free_transfers - incoming.length) + 1,
        ),
    seconds,
  };
}

export function solvePriorityPreferences(
  solver: LpSolver,
  published: DevicePlanDocument,
  entry: DevicePlanEntry,
  baseline: DevicePlanAnswer,
  program: PriorityProgram,
  now: () => number = () => performance.now(),
): DevicePlanAnswer {
  const started = now();
  const ordered = inSolverOrder(published);
  const document = {
    ...ordered,
    players: ordered.players.map((p) => ({
      ...p,
      expected_points: p.coefficients[2] / ordered.rules.expected_points_scale,
    })),
  };
  const hard = oneWeekPreferences(baseline.preferences);
  if (
    !hard?.net_points_priority ||
    !Number.isInteger(program.max_total_cost_tenths) ||
    program.max_total_cost_tenths < 0 ||
    program.max_total_cost_tenths > 1000
  )
    throw new Error("Invalid priority domain.");
  const requested = program.preferences
    .map((item) => ({
      rules: oneWeekPreferences(checkedPreferences(item.rules))!,
      priority: item.priority ?? 2,
      identity: priorityRuleIdentity(item.rules),
    }))
    .sort((a, b) => (a.identity < b.identity ? -1 : a.identity > b.identity ? 1 : 0));
  if (requested.some((item) => item.rules.net_points_priority || item.rules.frozen_weeks?.length))
    throw new Error("Unsupported priority rule.");
  if (
    !requested.length ||
    requested.length > 16 ||
    new Set(requested.map((r) => r.identity)).size !== requested.length ||
    requested.some((r) => !preferencesKey(r.rules) || ![1, 2, 3].includes(r.priority))
  )
    throw new Error("Invalid priority preferences.");
  const problem = memberWeekProblem(document, entry, { preferences: hard, chip: baseline.chip });
  const points = [...problem.objective];
  const soft = requested.map((item) =>
    hardPreferenceRows(document, entry, item.rules, baseline.chip),
  );
  let best = referenceValues(document, entry, {
    squad: baseline.squad,
    startingXi: baseline.starting_xi,
    captain: baseline.captain,
    proved: !baseline.restricted,
  });
  if (!holds(problem.rows, best))
    throw new Error("The required main witness does not fit this model.");
  // J is recomputed from the witness, never read from a numeric reference claim.
  const reference = Math.round(valueOf(points, best));
  const floor =
    reference -
    Math.floor((program.max_total_cost_tenths * document.rules.expected_points_scale) / 10);
  problem.rows.push(row("priority_floor", points, ">=", floor));
  const bounds = new Map(problem.generals.map((b) => [b.variable, [b.lower, b.upper] as const]));
  for (const name of problem.binaries) bounds.set(name, [0, 1]);
  let serial = 0;
  const imply = (selector: string, condition: LpRow) => {
    if (condition.sense === "=") {
      imply(selector, { ...condition, sense: ">=" });
      imply(selector, { ...condition, sense: "<=" });
      return;
    }
    const sign = condition.sense === ">=" ? 1 : -1;
    const terms = condition.terms.map((t) => term(sign * t.coefficient, t.variable));
    const target = sign * condition.rhs;
    const minimum = terms.reduce((sum, t) => {
      const range = bounds.get(t.variable);
      if (!range || !range.every(Number.isFinite))
        throw new Error("Unbounded preference implication.");
      return sum + Math.min(t.coefficient * range[0], t.coefficient * range[1]);
    }, 0);
    const big = Math.max(0, target - minimum);
    problem.rows.push(
      row(`priority_gate_${serial++}`, [...terms, term(-big, selector)], ">=", target - big),
    );
  };
  requested.forEach((_, i) => {
    const selector = `want${i}`;
    problem.binaries.push(selector);
    soft[i]!.forEach((condition) => imply(selector, condition));
  });
  const completed: (1 | 2 | 3)[] = [];
  let exhausted = false;
  const normalize = (solution: Solution): Values | null => {
    const values = checkedColumns(problem, solution);
    if (!values) return null;
    const incoming = document.players.reduce(
      (n, p, i) => n + Number(!entry.held.includes(p.id) && values[`s${i}`]?.Primal === 1),
      0,
    );
    values.paid = { Primal: Math.max(0, incoming - entry.free_transfers) };
    soft.forEach((conditions, i) => {
      values[`want${i}`] = { Primal: Number(holds(conditions, values)) };
    });
    return holds(problem.rows, values) ? values : null;
  };
  soft.forEach((conditions, i) => {
    best[`want${i}`] = { Primal: Number(holds(conditions, best)) };
  });
  const pointsReserve = (solver.remainingSeconds?.() ?? 0) / 4;
  for (const level of [1, 2, 3] as const) {
    const terms = requested.flatMap((item, i) =>
      item.priority === level ? [term(1, `want${i}`)] : [],
    );
    if (!terms.length) continue;
    const countSeconds = (solver.remainingSeconds?.() ?? Infinity) - pointsReserve;
    if (countSeconds <= 0) {
      exhausted = true;
      break;
    }
    problem.objective = terms;
    const solution = solver.solve(
      lpText(problem),
      Number.isFinite(countSeconds) ? { ...EXACT, time_limit: countSeconds } : EXACT,
    );
    if (!["Optimal", "Time limit reached", "Iteration limit reached"].includes(solution.Status))
      throw new DevicePlanRefused(solution.Status, "plan");
    const candidate = normalize(solution);
    if (!candidate && solution.Status === "Optimal")
      throw new DevicePlanRefused("invalid priority witness", "plan");
    const count = candidate && valueOf(terms, candidate);
    if (!candidate || count === null || (solution.Status !== "Optimal" && count !== terms.length)) {
      exhausted = true;
      break;
    }
    if (valueOf(terms, best) !== count || valueOf(points, candidate) > valueOf(points, best))
      best = candidate;
    problem.rows.push(row(`priority_fixed_${level}`, terms, "=", count));
    completed.push(level);
  }
  if (completed.length) {
    if ((solver.remainingSeconds?.() ?? Infinity) <= 0) exhausted = true;
    else {
      problem.objective = points;
      problem.rows.push(row("priority_incumbent", points, ">=", valueOf(points, best)));
      const solution = solver.solve(lpText(problem), EXACT);
      if (solution.Status === "Optimal" || solution.Status === "Iteration limit reached") {
        const candidate = normalize(solution);
        if (candidate) best = candidate;
        else if (solution.Status === "Optimal")
          throw new DevicePlanRefused("invalid points witness", "plan");
        if (solution.Status !== "Optimal") exhausted = true;
      } else if (solution.Status === "Time limit reached") exhausted = true;
      else throw new DevicePlanRefused(solution.Status, "plan");
    }
  }
  const satisfied: string[] = [];
  const leftOut: string[] = [];
  const unsearched: string[] = [];
  requested.forEach((rule, i) => {
    if (!completed.includes(rule.priority)) unsearched.push(rule.identity);
    else if (holds(soft[i]!, best)) satisfied.push(rule.identity);
    else leftOut.push(rule.identity);
  });
  const score = Math.round(valueOf(points, best));
  if (score < floor) throw new Error("The priority plan exceeds its total concession.");
  const metadata: PriorityResult = {
    contract_version: "llmopt_priority_result_v1",
    satisfied,
    left_out: leftOut,
    unsearched,
    completed_priorities: completed,
    reference_proved: !baseline.restricted,
    total_cost: (reference - score) / document.rules.expected_points_scale,
    budget_exhausted: exhausted,
  };
  return answerFor(document, entry, baseline, best, points, metadata, (now() - started) / 1000);
}
