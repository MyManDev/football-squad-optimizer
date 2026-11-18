import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { beforeAll, describe, expect, it } from "vitest";
import { checkedPreferences } from "../advice/decisionPreferences";
import { solveAlternatives, transferDecisionId } from "./alternatives";
import { oneWeekPreferences } from "./preferences";
import { solvePlan, solveWeek } from "./solve/week";
import type { LpSolver } from "./lp/problem";
import type { DevicePlanDocument, DevicePlanEntry } from "./types";

const require = createRequire(import.meta.url);
let solver: LpSolver;
beforeAll(async () => {
  const load = (await import("highs")).default;
  solver = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);

export const tinyDocument: DevicePlanDocument = {
  contract_version: "league_device_plan_v1",
  league_id: 1,
  source_snapshot_id: "hard-rules",
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
    [0, 1].map((b) => {
      const points = [5, 4, 10, 6][k]! - b;
      return {
        id: 2 * k + b + 1,
        name: `p${2 * k + b + 1}`,
        short_name: `p${2 * k + b + 1}`,
        position,
        team: b ? "B" : "A",
        buy_tenths: b ? 40 : 50,
        expected_points: points,
        coefficients: [points, 9 * points, 10 * points] as [number, number, number],
      };
    }),
  ),
};
export const tinyEntry: DevicePlanEntry = {
  held: [1, 3, 5, 7],
  bank_tenths: 0,
  free_transfers: 4,
  sell_tenths: {},
};
const p = (value: object) => checkedPreferences(value);

describe("hard one-week rules", () => {
  it("keeps, includes and avoids explicit players", () => {
    const answer = solvePlan(solver, tinyDocument, tinyEntry, () => 0, null, {
      preferences: p({ keep_players: [1], include_players: [8], avoid_players: [3] }),
    });
    expect(answer.squad).toContain(1);
    expect(answer.squad).toContain(8);
    expect(answer.squad).not.toContain(3);
    expect(answer.free_transfers_before).toBe(4);
  });
  it("applies dated purchases and club counts to arrivals", () => {
    const answer = solveWeek(solver, tinyDocument, tinyEntry, {
      preferences: p({
        week_rules: [{ week: 1, rules: { buy_players: [2] } }],
        club_counts: [{ club: "B", count: 2, scope: "transfers_in" }],
      }),
    });
    expect(answer?.squad).toContain(2);
    expect(answer?.squad.filter((id) => id % 2 === 0)).toHaveLength(2);
  });
  it("holds transfers and refuses a conflicting rebuild", () => {
    const preferences = p({ hold_transfers: true });
    expect(solveWeek(solver, tinyDocument, tinyEntry, { preferences })?.squad).toEqual(
      tinyEntry.held,
    );
    expect(
      solveWeek(solver, tinyDocument, tinyEntry, { preferences, chip: "wildcard" }),
    ).toBeNull();
  });
  it("caps actual hit charges without forbidding free rebuild transfers", () => {
    const entry = { ...tinyEntry, free_transfers: 1 };
    const preferences = p({ include_players: [2, 8], no_hits: true, max_hit_points: 0 });
    expect(solveWeek(solver, tinyDocument, entry, { preferences })).toBeNull();
    const answer = solvePlan(solver, tinyDocument, entry, () => 0, "wildcard", { preferences });
    expect(answer.transfer_hit_points).toBe(0);
    expect(answer.transfers_in.length).toBeGreaterThan(1);
  });
  it("keeps a persistent bank floor and saved chips", () => {
    const answer = solvePlan(solver, tinyDocument, tinyEntry, () => 0, null, {
      preferences: p({ min_bank: { tenths: 25 }, save_chips: true }),
    });
    expect(answer.bank_after_tenths).toBeGreaterThanOrEqual(25);
    expect(
      solveWeek(solver, tinyDocument, tinyEntry, {
        chip: "bboost",
        preferences: p({ save_chips: true }),
      }),
    ).toBeNull();
  });
  it("refuses future-week and scenario families explicitly", () => {
    expect(() =>
      oneWeekPreferences(p({ week_rules: [{ week: 2, rules: { no_hits: true } }] })),
    ).toThrow();
    expect(() =>
      oneWeekPreferences(p({ scenario: { kind: "unavailable", player_id: 1 } })),
    ).toThrow();
  });
});

describe("independent transfer-package oracle", () => {
  it("matches every Pareto package, preserves hard rules and never repeats a decision", () => {
    const preferences = p({ keep_players: [1, 5, 7], no_hits: true });
    const choices = solveAlternatives(solver, tinyDocument, tinyEntry, preferences, { gap: 0 });
    const all: { squad: number[]; vector: number[] }[] = [];
    // Four independent A/B choices give all sixteen legal final squads.
    for (let mask = 0; mask < 16; mask++) {
      const squad = [0, 1, 2, 3].map((k) => 2 * k + 1 + ((mask >> k) & 1));
      if (![1, 5, 7].every((id) => squad.includes(id))) continue;
      const pts = (id: number) => tinyDocument.players[id - 1]!.expected_points;
      const score = Math.max(
        ...[1, 2].map((third) => {
          const xi = [squad[0]!, squad[third]!, squad[3]!];
          return xi.reduce((sum, id) => sum + pts(id), 0) + Math.max(...xi.map(pts));
        }),
      );
      const moves = squad.filter((id) => !tinyEntry.held.includes(id)).length;
      const bank = 10 * moves;
      const free = Math.min(5, Math.max(0, 4 - moves) + 1);
      all.push({ squad, vector: [score, bank, 0, free] });
    }
    const best = Math.max(...all.map((a) => a.vector[0]!));
    const front = all.filter(
      (a) =>
        a.vector[0] === best &&
        !all.some(
          (b) =>
            b.vector.every((v, i) => v >= a.vector[i]!) &&
            b.vector.some((v, i) => v > a.vector[i]!),
        ),
    );
    expect(choices.map((c) => c.squad.join(",")).sort()).toEqual(
      front.map((c) => c.squad.join(",")).sort(),
    );
    expect(choices).toHaveLength(2);
    expect(new Set(choices.map((c) => c.decisionId)).size).toBe(choices.length);
    for (const choice of choices) {
      expect([1, 5, 7].every((id) => choice.squad.includes(id))).toBe(true);
      expect(choice.hitPoints).toBe(0);
    }
  });
  it("caps the displayed set at three and excludes captain-only variants", () => {
    const choices = solveAlternatives(solver, tinyDocument, tinyEntry, p({ no_hits: true }));
    expect(choices.length).toBeLessThanOrEqual(3);
    expect(choices.length).toBeGreaterThan(1);
    expect(new Set(choices.map((a) => a.decisionId)).size).toBe(choices.length);
    expect(transferDecisionId([3, 1, 7, 5], null)).toBe(transferDecisionId([1, 3, 5, 7], null));
  });
});
