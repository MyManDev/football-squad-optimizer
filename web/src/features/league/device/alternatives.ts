/** Proved Pareto choices with distinct one-week transfer decisions. */
import { checkedPreferences, type DecisionPreferences } from "../advice/decisionPreferences";
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
import { oneWeekPreferences } from "./preferences";
import { inSolverOrder, DevicePlanRefused, type WeekSolution } from "./solve/week";
import { DEVICE_ALTERNATIVE_SECONDS } from "./solve/ceiling";
import { rebuilds } from "./strategies/chips";
import type { DeviceChip, DevicePlanDocument, DevicePlanEntry } from "./types";

export const DEFAULT_ALTERNATIVE_GAP = 6.3;

export interface DeviceAlternative extends WeekSolution {
  decisionId: string;
  bankTenths: number;
  hitPoints: number;
  freeTransfersAfter: number;
  netPoints: number;
}

const evaluate = (terms: readonly LpTerm[], answer: Solution) =>
  Math.round(
    terms.reduce((sum, t) => sum + t.coefficient * (answer.Columns[t.variable]?.Primal ?? 0), 0),
  );

export function transferDecisionId(squad: readonly number[], chip: DeviceChip | null): string {
  return JSON.stringify([chip, [...squad].sort((a, b) => a - b)]);
}

export function dominates(a: DeviceAlternative, b: DeviceAlternative): boolean {
  const one = [a.objectiveScaled, a.bankTenths, -a.hitPoints, a.freeTransfersAfter];
  const two = [b.objectiveScaled, b.bankTenths, -b.hitPoints, b.freeTransfersAfter];
  return one.every((value, i) => value >= two[i]!) && one.some((value, i) => value > two[i]!);
}

/** Each found choice is optimal in points and then resources within the undominated region.
 * A later choice must improve a resource or exactly match the entire previous vector.
 * Equal vectors remain distinct choices; previously selected squads are excluded separately.
 */
export function solveAlternatives(
  solver: LpSolver,
  published: DevicePlanDocument,
  entry: DevicePlanEntry,
  preferences?: DecisionPreferences,
  {
    gap = DEFAULT_ALTERNATIVE_GAP,
    count = 3,
    chip = null,
    main,
    onAlternative,
    now = () => performance.now(),
  }: {
    gap?: number;
    count?: number;
    chip?: DeviceChip | null;
    main?: DeviceAlternative;
    onAlternative?: (choice: DeviceAlternative) => void;
    now?: () => number;
  } = {},
): DeviceAlternative[] {
  if (
    !Number.isFinite(gap) ||
    gap < 0 ||
    gap > 100 ||
    !Number.isInteger(count) ||
    count < 1 ||
    count > 3
  )
    throw new Error("Invalid alternative bound.");
  const document = inSolverOrder(published);
  const p = checkedPreferences({ ...oneWeekPreferences(preferences), net_points_priority: true });
  const held = new Set(entry.held);
  const arrivals = document.players.flatMap((player, i) =>
    held.has(player.id) ? [] : [term(1, `s${i}`)],
  );
  const sell = (id: number, buy: number) => entry.sell_tenths[String(id)] ?? buy;
  const cash =
    chip === "freehit"
      ? entry.bank_tenths
      : entry.bank_tenths +
        document.players.reduce(
          (sum, player) => sum + (held.has(player.id) ? sell(player.id, player.buy_tenths) : 0),
          0,
        );
  const bank: LpTerm[] =
    chip === "freehit"
      ? []
      : document.players.map((player, i) =>
          term(
            -(held.has(player.id) ? sell(player.id, player.buy_tenths) : player.buy_tenths),
            `s${i}`,
          ),
        );
  const hit: LpTerm[] =
    rebuilds(chip) || document.rules.hit_points_charged === 0 ? [] : [term(-1, "paid")];
  const negativeMoves = arrivals.map((t) => term(-t.coefficient, t.variable));
  const result: DeviceAlternative[] = main ? [main] : [];
  let floor = main
    ? Math.ceil(main.objectiveScaled - gap * document.rules.expected_points_scale)
    : undefined;
  const scalar = (terms: LpTerm[], target: number) => row("unused", terms, ">=", target);
  const freeAfter = (moves: number) =>
    Math.min(
      document.rules.max_free_transfers,
      (rebuilds(chip) ? entry.free_transfers : Math.max(0, entry.free_transfers - moves)) + 1,
    );

  for (let attempt = result.length; attempt < count; attempt++) {
    const deadline = now() + DEVICE_ALTERNATIVE_SECONDS * 1000;
    const problem = memberWeekProblem(document, entry, {
      chip,
      preferences: p,
      excludedSquads: result.map((r) => r.squad),
      minimumObjectiveScaled: floor,
    });
    // Give paid its economic value even when a dominance branch fixes a resource.
    problem.rows = problem.rows.filter((r) => r.name !== "paid");
    if (rebuilds(chip)) problem.rows.push(row("exact_paid", [term(1, "paid")], "=", 0));
    else {
      const n = document.rules.squad_size,
        f = entry.free_transfers;
      problem.binaries.push("charge");
      problem.rows.push(
        row("paid_lo", [term(1, "paid"), ...negativeMoves], ">=", -f),
        row("paid_hi", [term(1, "paid"), ...negativeMoves, term(f, "charge")], "<=", 0),
        row("paid_zero", [term(1, "paid"), term(-n, "charge")], "<=", 0),
        row("charge_lo", [...arrivals, term(-(f + 1), "charge")], ">=", 0),
        row("charge_hi", [...arrivals, term(-n, "charge")], "<=", f),
      );
    }
    const points = [...problem.objective];
    let serial = 0;
    const bounds = (terms: readonly LpTerm[]): [number, number] => {
      let lo = 0,
        hi = 0;
      for (const t of terms) {
        const limit = t.variable === "paid" ? document.rules.squad_size : 1;
        lo += Math.min(0, t.coefficient * limit);
        hi += Math.max(0, t.coefficient * limit);
      }
      return [lo, hi];
    };
    const imply = (selector: string, condition: LpRow) => {
      if (condition.sense === "=") {
        imply(selector, { ...condition, sense: ">=" });
        imply(selector, { ...condition, sense: "<=" });
        return;
      }
      const sign = condition.sense === ">=" ? 1 : -1;
      const terms = condition.terms.map((t) => term(sign * t.coefficient, t.variable));
      const target = sign * condition.rhs;
      const big = Math.max(0, target - bounds(terms)[0]);
      problem.rows.push(
        row(`gate${serial++}`, [...terms, term(-big, selector)], ">=", target - big),
      );
    };
    for (const [k, previous] of result.entries()) {
      const gates: string[] = [];
      const vectors: [LpTerm[], number][] = [
        [points, previous.objectiveScaled],
        [bank, previous.bankTenths - cash],
        [hit, hit.length ? -previous.hitPoints / document.rules.hit_points_charged : 0],
      ];
      vectors.forEach(([terms, value], metric) => {
        if (!terms.length) return;
        const name = `better${k}_${metric}`;
        problem.binaries.push(name);
        gates.push(name);
        imply(name, scalar(terms, value + 1));
      });
      if (!rebuilds(chip) && previous.freeTransfersAfter < document.rules.max_free_transfers) {
        const name = `free${k}`;
        problem.binaries.push(name);
        gates.push(name);
        imply(
          name,
          row("free", arrivals, "<=", entry.free_transfers - previous.freeTransfersAfter),
        );
      }
      const equal = `equal${k}`;
      problem.binaries.push(equal);
      gates.push(equal);
      for (const [terms, value] of vectors) imply(equal, row("equal", terms, "=", value));
      if (!rebuilds(chip)) {
        const next = previous.freeTransfersAfter;
        const moves = entry.free_transfers + 1 - next;
        if (next === document.rules.max_free_transfers)
          imply(equal, row("free_equal", arrivals, "<=", moves));
        else if (next === 1) imply(equal, row("free_equal", arrivals, ">=", entry.free_transfers));
        else imply(equal, row("free_equal", arrivals, "=", moves));
      }
      problem.rows.push(
        row(
          `any${k}`,
          gates.map((g) => term(1, g)),
          ">=",
          1,
        ),
      );
    }
    let answer: Solution | null = null;
    for (const [tier, objective] of [points, bank, hit, negativeMoves].entries()) {
      problem.sense = "Maximize";
      problem.objective = objective;
      const model = lpText(problem);
      const seconds = Math.min((deadline - now()) / 1000, solver.remainingSeconds?.() ?? Infinity);
      if (seconds <= 0) return result;
      const solved = solver.solve(model, { ...EXACT, time_limit: seconds });
      if (now() >= deadline || (solver.remainingSeconds?.() ?? Infinity) <= 0) return result;
      if (solved.Status === "Infeasible" && tier === 0) break;
      if (solved.Status === "Infeasible")
        throw new Error("Resource tie break contradicts its completed optimum.");
      if (solved.Status !== "Optimal") {
        // Completed choices survive an unproved or interrupted later alternative.
        if (result.length) return result;
        throw new DevicePlanRefused(solved.Status, "plan");
      }
      answer = solved;
      const value = evaluate(objective, solved);
      problem.rows.push(row(`lex${tier}`, objective, "=", value));
    }
    if (!answer) break;
    const ids = document.players.map((player) => player.id);
    const squad = chosenIds(answer, ids, "s");
    const moves = squad.filter((id) => !held.has(id)).length;
    const objectiveScaled = evaluate(points, answer);
    if (floor === undefined)
      floor = Math.ceil(objectiveScaled - gap * document.rules.expected_points_scale);
    const candidate: DeviceAlternative = {
      objectiveScaled,
      netPoints: objectiveScaled / document.rules.expected_points_scale,
      squad,
      startingXi: chosenIds(answer, ids, "x"),
      captain: chosenIds(answer, ids, "c")[0]!,
      decisionId: transferDecisionId(squad, chip),
      bankTenths: cash + evaluate(bank, answer),
      hitPoints:
        (rebuilds(chip) ? 0 : Math.max(0, moves - entry.free_transfers)) *
        document.rules.hit_points_charged,
      freeTransfersAfter: freeAfter(moves),
    };
    if (
      result.some(
        (prior) => prior.decisionId === candidate.decisionId || dominates(prior, candidate),
      )
    )
      throw new Error("An excluded or dominated decision was returned.");
    result.push(candidate);
    onAlternative?.(candidate);
  }
  return result;
}
