import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { beforeAll, describe, expect, it } from "vitest";
import { checkedPreferences, type DecisionPreferences } from "../advice/decisionPreferences";
import { priorityRuleIdentity, type PriorityProgram } from "../advice/preferenceBundle";
import { solvePriorityPreferences } from "./priority";
import { solvePlan } from "./solve/week";
import { solveRequest } from "./requests";
import type { LpSolver } from "./lp/problem";
import type { DevicePlanDocument, DevicePlanEntry } from "./types";

let solver: LpSolver;
beforeAll(async () => {
  const require = createRequire(import.meta.url);
  const load = (await import("highs")).default;
  solver = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);
const document: DevicePlanDocument = {
  contract_version: "league_device_plan_v1",
  league_id: 1,
  source_snapshot_id: "priority-oracle",
  season: "2026-27",
  gameweek: 8,
  policy_id: "tiny",
  rules: {
    squad_size: 4,
    starting_size: 3,
    squad_position_limits: { GK: 1, DEF: 1, MID: 1, FWD: 1 },
    starting_position_min: { GK: 1, DEF: 0, MID: 0, FWD: 1 },
    starting_position_max: { GK: 1, DEF: 1, MID: 1, FWD: 1 },
    max_players_per_team: 4,
    max_free_transfers: 5,
    hit_cost_scaled: 80,
    hit_points_charged: 4,
    expected_points_scale: 10,
  },
  players: ["GK", "DEF", "MID", "FWD"].flatMap((position, k) =>
    [0, 1].map((variant) => {
      const points = [5, 4, 10, 6][k]! - variant;
      return {
        id: 2 * k + variant + 1,
        name: `p${2 * k + variant + 1}`,
        short_name: `p${2 * k + variant + 1}`,
        position,
        team: variant ? "B" : "A",
        buy_tenths: variant ? 40 : 50,
        expected_points: points,
        coefficients: [points, 9 * points, 10 * points] as [number, number, number],
      };
    }),
  ),
};
const entry: DevicePlanEntry = {
  held: [1, 3, 5, 7],
  bank_tenths: 0,
  free_transfers: 4,
  sell_tenths: {},
};
const hard = checkedPreferences({ net_points_priority: true, save_chips: true });
const preferences = [
  { rules: checkedPreferences({ include_players: [2] }), priority: 1 as const },
  { rules: checkedPreferences({ avoid_players: [5] }), priority: 2 as const },
  { rules: checkedPreferences({ include_players: [8] }), priority: 3 as const },
];
const program: PriorityProgram = { preferences, max_total_cost_tenths: 15 };

/** Independent enumeration: all sixteen position-complete packages, legal XIs and captains. */
function oracle(rules: DecisionPreferences, request: PriorityProgram, allowance = 4) {
  const candidates: {
    squad: number[];
    xi: number[];
    captain: number;
    score: number;
    bank: number;
    hit: number;
  }[] = [];
  const byId = new Map(document.players.map((p) => [p.id, p]));
  const accepts = (p: DecisionPreferences, c: (typeof candidates)[number]) => {
    const arrivals = c.squad.filter((id) => !entry.held.includes(id));
    return (
      p.keep_players.every((id) => c.squad.includes(id)) &&
      p.avoid_players.every((id) => !c.squad.includes(id)) &&
      (p.include_players ?? []).every((id) => c.squad.includes(id)) &&
      (!p.no_hits || c.hit === 0) &&
      (!p.hold_transfers || arrivals.length === 0) &&
      (p.max_hit_points === undefined || c.hit <= p.max_hit_points) &&
      c.bank >= Math.max(p.min_opening_bank_tenths ?? 0, p.min_bank?.tenths ?? 0) &&
      (p.club_counts ?? []).every(
        (club) =>
          (club.scope === "transfers_in" ? arrivals : c.squad).filter(
            (id) => byId.get(id)!.team === club.club,
          ).length === club.count,
      )
    );
  };
  for (let mask = 0; mask < 16; mask++) {
    const squad = [0, 1, 2, 3].map((i) => 2 * i + 1 + ((mask >> i) & 1));
    const incoming = squad.filter((id) => !entry.held.includes(id));
    const bank =
      entry.held.filter((id) => !squad.includes(id)).length * 50 -
      incoming.reduce((sum, id) => sum + byId.get(id)!.buy_tenths, 0);
    if (bank < 0) continue;
    const hit = Math.max(0, incoming.length - allowance) * 4;
    for (const middle of [1, 2]) {
      const xi = [squad[0]!, squad[middle]!, squad[3]!];
      for (const captain of xi) {
        const score = Math.round(
          10 *
            (xi.reduce((sum, id) => sum + byId.get(id)!.expected_points, 0) +
              byId.get(captain)!.expected_points -
              hit),
        );
        const candidate = { squad, xi, captain, score, bank, hit };
        if (accepts(rules, candidate)) candidates.push(candidate);
      }
    }
  }
  const reference = Math.max(...candidates.map((c) => c.score));
  const scored = candidates
    .filter((c) => c.score >= reference - request.max_total_cost_tenths)
    .map((c) => ({
      ...c,
      vector: [1, 2, 3]
        .map(
          (level) =>
            request.preferences.filter((p) => p.priority === level && accepts(p.rules, c)).length,
        )
        .concat(c.score),
    }));
  const compare = (a: number[], b: number[]) => {
    for (let i = 0; i < a.length; i++) if (a[i] !== b[i]) return a[i]! - b[i]!;
    return 0;
  };
  const best = scored.reduce((a, b) => (compare(a.vector, b.vector) >= 0 ? a : b));
  return {
    reference,
    vector: best.vector,
    packages: scored
      .filter((c) => compare(c.vector, best.vector) === 0)
      .map((c) => JSON.stringify(c.squad)),
  };
}

describe("device priority counts", () => {
  it.each(["all", "incomplete", "fractional", "missing"])(
    "certifies only complete integral all-true count incumbents (%s)",
    (kind) => {
      const main = solvePlan(solver, document, entry, () => 0, null, { preferences: hard });
      const requested = {
        max_total_cost_tenths: 0,
        preferences: [
          {
            priority: 1 as const,
            rules: checkedPreferences(
              kind === "incomplete" ? { include_players: [2] } : { include_players: [5] },
            ),
          },
        ],
      };
      let calls = 0;
      const cutoff: LpSolver = {
        solve: (lp, options) => {
          calls++;
          const result = solver.solve(lp, options);
          if (calls !== 1) return result;
          const columns = { ...result.Columns };
          if (kind === "fractional") columns.s0 = { Primal: 0.51 };
          if (kind === "missing") delete columns.s0;
          return { ...result, Status: "Time limit reached", ObjectiveValue: 1e9, Columns: columns };
        },
      };
      const metadata = solvePriorityPreferences(
        cutoff,
        document,
        entry,
        main,
        requested,
      ).priority_preferences!;
      expect(metadata.completed_priorities).toEqual(kind === "all" ? [1] : []);
      expect(metadata.unsearched).toHaveLength(kind === "all" ? 0 : 1);
      expect(metadata.budget_exhausted).toBe(kind !== "all");
      expect(calls).toBe(kind === "all" ? 2 : 1);
    },
  );

  it.each(["Time limit reached", "Iteration limit reached", "Optimal"])(
    "keeps the best completed witness and distinguishes a points stop (%s)",
    (status) => {
      const main = solvePlan(solver, document, entry, () => 0, null, { preferences: hard });
      const requested = {
        max_total_cost_tenths: 100,
        preferences: [
          { priority: 1 as const, rules: checkedPreferences({ include_players: [2] }) },
          { priority: 2 as const, rules: checkedPreferences({ no_hits: true }) },
        ],
      };
      let calls = 0;
      const visited: LpSolver = {
        solve: (lp, options) => {
          calls++;
          // The first certified keeper choice carries player 8. The second count tries a worse
          // midfielder while retaining that forward. Both count witnesses attain the true bound.
          const pins =
            calls === 1
              ? ["first_mid: c4 = 1", "first_fwd: s7 = 1"]
              : calls === 2
                ? ["second_mid: c5 = 1", "second_fwd: s7 = 1"]
                : [];
          const result = solver.solve(
            lp.replace("Subject To", ["Subject To", ...pins].join("\n")),
            options,
          );
          expect(result.Status).toBe("Optimal");
          return calls === 3 ? { ...result, Status: status } : result;
        },
      };
      const answer = solvePriorityPreferences(visited, document, entry, main, requested);
      expect(answer.priority_preferences!.completed_priorities).toEqual([1, 2]);
      expect(answer.priority_preferences!.budget_exhausted).toBe(status !== "Optimal");
      expect(answer.objective_scaled).toBe(status === "Time limit reached" ? 290 : 300);
      expect(answer.priority_preferences!.total_cost).toBe(status === "Time limit reached" ? 2 : 1);
      expect(calls).toBe(3);
    },
  );

  it("uses the remaining points allowance after a weaker count has no witness", () => {
    const main = solvePlan(solver, document, entry, () => 0, null, { preferences: hard });
    let calls = 0;
    const seconds = [12, 10, 5];
    const cut: LpSolver = {
      remainingSeconds: () => seconds[calls] ?? 0,
      solve(lp, options) {
        calls++;
        if (calls === 2) return { Status: "Time limit reached", Columns: {}, ObjectiveValue: 1e9 };
        if (calls === 1) expect(options?.time_limit).toBe(9);
        return solver.solve(lp, options);
      },
    };
    const answer = solvePriorityPreferences(cut, document, entry, main, program);
    expect(calls).toBe(3);
    expect(answer.priority_preferences!.completed_priorities).toEqual([1]);
    expect(answer.priority_preferences!.unsearched).toHaveLength(2);
    expect(answer.priority_preferences!.budget_exhausted).toBe(true);
    expect(answer.objective_scaled).toBe(300);
  });

  it("uses the unproved main actually returned by the worker as J and refuses an invalid or missing main", () => {
    const input = { document, entry, preferences: hard };
    let calls = 0;
    const cutPrimary: LpSolver = {
      solve(lp, options) {
        calls++;
        const result = solver.solve(
          calls === 1 ? lp.replace("Subject To", "Subject To\nheld_mid: s5 = 1") : lp,
          options,
        );
        return calls === 1
          ? { ...result, Status: "Time limit reached", ObjectiveValue: 1e9 }
          : result;
      },
    };
    const main = solveRequest(cutPrimary, { ...input, priorityMain: true });
    expect(main.restricted).toBe(true);
    expect(main.objective_scaled).toBe(290);
    const preferenceBundle = {
      contract_version: "llmopt_preference_bundle_v1" as const,
      slots: [],
      prices: [],
      choices: [],
      program: {
        max_total_cost_tenths: 0,
        preferences: [{ priority: 2 as const, rules: checkedPreferences({ no_hits: true }) }],
      },
    };
    const priorityReference = {
      squad: main.squad,
      startingXi: main.starting_xi,
      captain: main.captain,
      proved: false,
    };
    const result = solveRequest(solver, { ...input, preferenceBundle, priorityReference });
    expect(result.squad).toEqual(main.squad);
    expect(result.restricted).toBe(true);
    const chosen = result.preference_bundle!.selected!.answer!;
    expect(chosen.priority_preferences).toMatchObject({ reference_proved: false, total_cost: -2 });
    expect(chosen.objective_scaled).toBe(310);
    expect(() => solveRequest(solver, { ...input, preferenceBundle })).toThrow(
      "missing confirmed main",
    );
    expect(() =>
      solveRequest(solver, {
        ...input,
        preferenceBundle,
        priorityReference: { ...priorityReference, captain: 999 },
      }),
    ).toThrow("Invalid main witness");
    calls = 0;
    expect(() => solveRequest(cutPrimary, input)).toThrow("Time limit reached");
  });
  it.each([0, 10, 15, 100])("matches every package and legal lineup at concession %i", (limit) => {
    const request = { ...program, max_total_cost_tenths: limit };
    const main = solvePlan(solver, document, entry, () => 0, null, { preferences: hard });
    const expected = oracle(hard, request);
    const answer = solvePriorityPreferences(solver, document, entry, main, request, () => 0);
    const metadata = answer.priority_preferences!;
    // Count independently from the returned physical decision, without reading indicator values.
    const counts = request.preferences.map(
      (p) =>
        p.rules.include_players?.every((id) => answer.squad.includes(id)) ??
        p.rules.avoid_players.every((id) => !answer.squad.includes(id)),
    );
    const actual = [1, 2, 3]
      .map(
        (level) => request.preferences.filter((p, i) => p.priority === level && counts[i]).length,
      )
      .concat(answer.objective_scaled);
    expect(actual).toEqual(expected.vector);
    expect(expected.packages).toContain(JSON.stringify(answer.squad));
    expect(metadata.total_cost).toBe((expected.reference - answer.objective_scaled) / 10);
    expect(metadata.completed_priorities).toEqual([1, 2, 3]);
    expect(metadata.unsearched).toEqual([]);
    expect([...metadata.satisfied].sort()).toEqual(
      request.preferences
        .filter((_, i) => counts[i])
        .map((p) => priorityRuleIdentity(p.rules))
        .sort(),
    );
    expect([...metadata.left_out].sort()).toEqual(
      request.preferences
        .filter((_, i) => !counts[i])
        .map((p) => priorityRuleIdentity(p.rules))
        .sort(),
    );
  });
  it("preserves hard rules and a binding joint allowance", () => {
    const required = checkedPreferences({
      ...hard,
      keep_players: [1],
      avoid_players: [3],
      min_bank: { tenths: 20 },
    });
    const request = { ...program, max_total_cost_tenths: 0 };
    const main = solvePlan(solver, document, entry, () => 0, null, { preferences: required });
    const answer = solvePriorityPreferences(solver, document, entry, main, request, () => 0);
    const expected = oracle(required, request);
    expect(answer.objective_scaled).toBe(expected.vector[3]);
    expect(answer.squad).toContain(1);
    expect(answer.squad).not.toContain(3);
    expect(answer.bank_after_tenths).toBeGreaterThanOrEqual(20);
    expect(answer.priority_preferences!.total_cost).toBeLessThanOrEqual(0);
  });
  it("does not give writing order a weight in an equal-priority layer", () => {
    const main = solvePlan(solver, document, entry, () => 0, null, { preferences: hard });
    const permutations = [
      [0, 1, 2],
      [0, 2, 1],
      [1, 0, 2],
      [1, 2, 0],
      [2, 0, 1],
      [2, 1, 0],
    ];
    const results = permutations.map((order) =>
      solvePriorityPreferences(
        solver,
        document,
        entry,
        main,
        { ...program, preferences: order.map((i) => ({ ...preferences[i]!, priority: 2 })) },
        () => 0,
      ),
    );
    expect(results.map((r) => [r.squad, r.starting_xi, r.captain, r.objective_scaled])).toEqual(
      Array(6).fill([
        results[0]!.squad,
        results[0]!.starting_xi,
        results[0]!.captain,
        results[0]!.objective_scaled,
      ]),
    );
  });
  it("starts no layer after the shared worker ceiling ends", () => {
    const main = solvePlan(solver, document, entry, () => 0, null, { preferences: hard });
    let calls = 0;
    const limited: LpSolver = {
      remainingSeconds: () => (calls === 0 ? 1 : 0),
      solve: (lp, options) => {
        calls++;
        return solver.solve(lp, options);
      },
    };
    const request = {
      ...program,
      preferences: [
        ...preferences.slice(0, 2),
        { rules: checkedPreferences({ no_hits: true }), priority: 3 as const },
      ],
    };
    const answer = solvePriorityPreferences(limited, document, entry, main, request, () => 0);
    expect(calls).toBe(1);
    expect(answer.priority_preferences!.completed_priorities).toEqual([1]);
    expect(answer.priority_preferences!.budget_exhausted).toBe(true);
    expect(answer.priority_preferences!.total_cost).toBeLessThanOrEqual(1.5);
    expect(answer.transfer_hit_points).toBe(0);
    const ids = request.preferences.map((p) => priorityRuleIdentity(p.rules));
    expect(answer.priority_preferences!.satisfied).toEqual([ids[0]]);
    expect(answer.priority_preferences!.left_out).toEqual([]);
    expect(answer.priority_preferences!.unsearched?.slice().sort()).toEqual(ids.slice(1).sort());
  });
  it("retains the last completed layer when the points tie break is interrupted", () => {
    const main = solvePlan(solver, document, entry, () => 0, null, { preferences: hard });
    let calls = 0;
    let last: ReturnType<LpSolver["solve"]> | undefined;
    const stopped: LpSolver = {
      solve: (lp, options) => {
        calls++;
        const result = solver.solve(lp, options);
        if (calls === 4)
          return { ...result, Status: "Time limit reached", Columns: {}, ObjectiveValue: 1e9 };
        last = result;
        return result;
      },
    };
    const answer = solvePriorityPreferences(stopped, document, entry, main, program, () => 0);
    expect(calls).toBe(4);
    expect(answer.priority_preferences?.completed_priorities).toEqual([1, 2, 3]);
    expect(answer.priority_preferences?.budget_exhausted).toBe(true);
    expect(answer.squad).toEqual(
      document.players.filter((_, i) => last!.Columns[`s${i}`]?.Primal === 1).map((p) => p.id),
    );
    expect(answer.priority_preferences!.total_cost).toBeLessThanOrEqual(1.5);
  });
  it("refuses solver errors instead of reporting them as exhausted time", () => {
    const main = solvePlan(solver, document, entry, () => 0, null, { preferences: hard });
    expect(() =>
      solvePriorityPreferences(
        { solve: () => ({ Status: "Model error", ObjectiveValue: 0, Columns: {} }) },
        document,
        entry,
        main,
        program,
        () => 0,
      ),
    ).toThrow("Model error");
  });
  it("recomputes an unproved J from decisions rather than numeric claims", () => {
    const weak = solvePlan(solver, document, entry, () => 0, null, {
      preferences: checkedPreferences({
        ...hard,
        frozen_weeks: [
          { week: 1, transfers_in: [2, 4, 6, 8], transfers_out: [1, 3, 5, 7], chip: null },
        ],
      }),
    });
    const main = {
      ...weak,
      preferences: hard,
      restricted: true,
      objective: 1e9,
      objective_scaled: 1e9,
      expected_own_points: 1e9,
    };
    const answer = solvePriorityPreferences(
      solver,
      document,
      entry,
      main,
      {
        max_total_cost_tenths: 0,
        preferences: [{ priority: 2, rules: checkedPreferences({ save_chips: true }) }],
      },
      () => 0,
    );
    expect(answer.priority_preferences!.reference_proved).toBe(false);
    expect(answer.priority_preferences!.total_cost).toBeLessThan(0);
    expect(answer.objective_scaled).toBe(310);
  });
});
