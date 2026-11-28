import { describe, expect, it } from "vitest";
import type { DevicePlanDocument, DevicePlanEntry } from "../types";
import { horizonInputs, horizonProblem, horizonRanks, type HorizonInputs } from "./horizon";
import { reduceHorizonPool } from "./reduce";

function world(
  count: number,
  clubs = Array.from({ length: count }, (_, i) => (i < 5 ? `held-${i}` : `choice-${i}`)),
) {
  const player = (id: number, team: string, coefficients: [number, number, number]) => ({
    id,
    team,
    position: "MID",
    name: String(id),
    short_name: String(id),
    buy_tenths: 50,
    expected_points: coefficients[2],
    coefficients,
  });
  const players = [
    ...Array.from({ length: 15 }, (_, i) => player(i + 1, `held-${i % 5}`, [10, 20, 30])),
    ...clubs.map((club, i) => player(100 + i, club, [2, 3, 4])),
    player(999, "target", [1, 2, 3]),
  ];
  const document: DevicePlanDocument = {
    contract_version: "league_device_plan_v1",
    league_id: 0,
    season: "2026-27",
    gameweek: 12,
    source_snapshot_id: "synthetic",
    policy_id: "synthetic",
    rules: {
      squad_size: 15,
      starting_size: 11,
      squad_position_limits: { MID: 15 },
      starting_position_min: { MID: 11 },
      starting_position_max: { MID: 11 },
      max_players_per_team: 3,
      max_free_transfers: 5,
      hit_cost_scaled: 4,
      hit_points_charged: 4,
      expected_points_scale: 1,
    },
    players,
  };
  const inputs: HorizonInputs = {
    contract_version: "league_device_horizon_v1",
    windows: [3, 5],
    rules: {
      max_transfers_per_gameweek: 1,
      free_transfer_accrual: 1,
      bench_weight: 0.1,
      objective_weight_scale: 1,
      horizon_discount_factor: 1,
      banked_transfer_value_scaled: 0,
      acquisition_sell_on_fee: 0.5,
    },
    weeks: Array.from({ length: 5 }, (_, w) => ({
      gameweek: 12 + w,
      discount_weight: 1,
      players: players.map(({ id, buy_tenths, expected_points, coefficients }) => ({
        id,
        buy_tenths,
        expected_points,
        coefficients: [...coefficients],
      })),
    })),
  };
  Object.assign(document, { horizon: inputs });
  const held = players.slice(0, 15);
  const entry: DevicePlanEntry = {
    held: held.map((p) => p.id),
    bank_tenths: 0,
    free_transfers: 0,
    sell_tenths: Object.fromEntries(held.map((p) => [p.id, p.buy_tenths])),
  };
  return { document, entry, inputs, target: players.length - 1 };
}

describe("whole-window dominance certificate", () => {
  it.each([
    [3, 7, false],
    [3, 8, true],
    [5, 9, false],
    [5, 10, true],
  ] as const)("H%s with %s distinct-club choices, removal=%s", (window, count, removed) => {
    const w = world(count);
    const r = reduceHorizonPool(w.document, w.entry, w.inputs, window);
    expect(!r.indices.includes(w.target)).toBe(removed);
    expect(r.purchaseUnionLimit).toBe(window);
    expect(r.fullClubUnionLimit).toBe(window === 3 ? 5 : 6);
  });

  it("retains a seven-club choice below the H3 whole-window threshold", () => {
    const w = world(7);
    expect(reduceHorizonPool(w.document, w.entry, w.inputs, 3).indices).toContain(w.target);
  });

  it("counts many choices in a few potentially full clubs conservatively", () => {
    const w = world(
      20,
      Array.from({ length: 20 }, (_, i) => `held-${i % 5}`),
    );
    expect(reduceHorizonPool(w.document, w.entry, w.inputs, 3).indices).toContain(w.target);
  });

  it.each([3, 5] as const)("uses the same-club exception at H%s", (window) => {
    const w = world(
      window,
      Array.from({ length: window }, () => "target"),
    );
    expect(reduceHorizonPool(w.document, w.entry, w.inputs, window).indices).not.toContain(
      w.target,
    );
    const [removed] = w.document.players.splice(15, 1);
    for (const week of w.inputs.weeks)
      week.players = week.players.filter((player) => player.id !== removed!.id);
    expect(reduceHorizonPool(w.document, w.entry, w.inputs, window).indices).toContain(
      w.target - 1,
    );
  });

  it("preserves holdings, sale lots and explicit pinned players as both p and q", () => {
    const w = world(8);
    expect(reduceHorizonPool(w.document, w.entry, w.inputs, 3).indices).not.toContain(w.target);
    expect(reduceHorizonPool(w.document, w.entry, w.inputs, 3, [999]).indices).toContain(w.target);
    expect(reduceHorizonPool(w.document, w.entry, w.inputs, 3, [107]).indices).toContain(w.target);
    w.entry.sell_tenths["107"] = 50;
    expect(reduceHorizonPool(w.document, w.entry, w.inputs, 3).indices).toContain(w.target);
    // Isolate held-q exclusion in p's own club, so the changed initial club
    // distribution cannot independently strengthen the full-club bound.
    const heldWorld = world(3, ["target", "target", "target"]);
    expect(
      reduceHorizonPool(heldWorld.document, heldWorld.entry, heldWorld.inputs, 3).indices,
    ).not.toContain(heldWorld.target);
    heldWorld.entry.held[0] = 100;
    heldWorld.entry.sell_tenths["100"] = 50;
    // The displaced player's explicit sale key remains protected too.
    const r = reduceHorizonPool(heldWorld.document, heldWorld.entry, heldWorld.inputs, 3);
    expect(r.indices).toContain(heldWorld.target);
    expect(r.indices).toContain(15);
  });

  it("requires every week's squad, starter and captain coefficient, frozen price and position", () => {
    for (const family of [0, 1, 2]) {
      const w = world(8);
      w.inputs.weeks[2]!.players[22]!.coefficients[family] = -1;
      expect(reduceHorizonPool(w.document, w.entry, w.inputs, 3).indices).toContain(w.target);
    }
    const expensive = world(8);
    expensive.document.players[22]!.buy_tenths = 51;
    for (const week of expensive.inputs.weeks) week.players[22]!.buy_tenths = 51;
    expect(
      reduceHorizonPool(expensive.document, expensive.entry, expensive.inputs, 3).indices,
    ).toContain(expensive.target);
    const otherPosition = world(8);
    otherPosition.document.players[22]!.position = "DEF";
    expect(
      reduceHorizonPool(otherPosition.document, otherPosition.entry, otherPosition.inputs, 3)
        .indices,
    ).toContain(otherPosition.target);
  });

  it("cannot fill a new club with three buys when only two remain after p", () => {
    const w = world(3, ["new-a", "new-b", "new-c"]);
    expect(reduceHorizonPool(w.document, w.entry, w.inputs, 3).indices).not.toContain(w.target);
  });

  it("shares the purchase budget between full clubs and held q outside them", () => {
    for (const [clubs, removed] of [
      [["spread-0", "spread-0"], false],
      [["spread-0", "spread-0", "spread-1"], true],
      [["spread-0", "spread-0", "spread-1", "spread-1"], true],
      [["spread-0", "spread-0", "spread-0", "spread-0"], false],
      [["spread-0", "spread-0", "spread-0", "spread-0", "empty"], true],
    ] as const) {
      const w = world(clubs.length, [...clubs]);
      for (let i = 0; i < 15; i += 1) w.document.players[i]!.team = `spread-${i}`;
      // A spread club has one initial player and costs two purchases to fill.
      // Filling it leaves zero purchases for q outside it. A two-q group has
      // zero surplus, while a four-q group has surplus two.
      expect(!reduceHorizonPool(w.document, w.entry, w.inputs, 3).indices.includes(w.target)).toBe(
        removed,
      );
    }
  });

  it.each([
    [4, false],
    [5, true],
  ] as const)(
    "keeps the empty subset when all club profits are negative: %s choices, removal=%s",
    (count, removed) => {
      const w = world(
        count,
        Array.from({ length: count }, (_, i) => `empty-${i}`),
      );
      // At H5 the budget is four. A new club costs three to fill but only
      // blocks one q, profit -2. The maximum surplus is the empty set's zero.
      expect(!reduceHorizonPool(w.document, w.entry, w.inputs, 5).indices.includes(w.target)).toBe(
        removed,
      );
    },
  );

  it("counts a zero-cost full club once and preserves p's own-club exception", () => {
    const w = world(8, [
      ...Array.from({ length: 5 }, () => "held-0"),
      "target",
      "target",
      "target",
    ]);
    expect(reduceHorizonPool(w.document, w.entry, w.inputs, 3).indices).not.toContain(w.target);
  });

  it("never uses a later original rank to justify a tied-primary replacement", () => {
    const w = world(8);
    w.document.players.unshift(w.document.players.pop()!);
    expect(reduceHorizonPool(w.document, w.entry, w.inputs, 3).indices).toContain(0);
  });

  it("fails closed for grandfathered clubs or negative price/lot values", () => {
    const w = world(8);
    w.document.players[1]!.team = "held-0";
    expect(reduceHorizonPool(w.document, w.entry, w.inputs, 3).after).toBe(
      w.document.players.length,
    );
    const negative = world(8);
    negative.entry.sell_tenths["1"] = -1;
    expect(reduceHorizonPool(negative.document, negative.entry, negative.inputs, 3).after).toBe(
      negative.document.players.length,
    );
  });
});

it("reduces LP variables without compacting original indices or any rank tier", () => {
  const w = world(8);
  const inputs = horizonInputs(w.document, 3);
  const problem = horizonProblem(w.document, w.entry, 3);
  const full = horizonProblem(w.document, w.entry, 3, "full");
  expect(problem.playerIndices).not.toContain(w.target);
  expect(full.playerIndices).toContain(w.target);
  expect(problem.binaries).not.toContain(`s0_${w.target}`);
  expect(full.binaries).toContain(`s0_${w.target}`);
  for (const family of ["c", "x", "s"] as const) {
    const rank = horizonRanks(w.document.players.length, 3, family, problem.playerIndices);
    expect(rank.find((t) => t.variable === `${family}2_22`)!.coefficient).toBe(70);
    expect(rank.some((t) => t.variable === `${family}2_${w.target}`)).toBe(false);
  }
  expect(w.document.players).toHaveLength(24);
  expect(inputs.weeks[0]!.players).toHaveLength(24);
});
