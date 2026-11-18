import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { beforeAll, describe, expect, it } from "vitest";

import { memberWeekProblem } from "./lp/memberWeek";
import { EXACT, lpText, row, term, type LpSolver } from "./lp/problem";
import { solvePlan, solveWeek } from "./solve/week";
import type { DeviceChip, DevicePlanDocument, DevicePlanEntry } from "./types";
import { whatIfAccount } from "./whatIf";

const require = createRequire(import.meta.url);
let solver: LpSolver;
beforeAll(async () => {
  const load = (await import("highs")).default;
  solver = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);

const positions = ["GK", "DEF", "MID", "FWD"];
const document: DevicePlanDocument = {
  contract_version: "league_device_plan_v1",
  league_id: 1,
  season: "2026-27",
  gameweek: 1,
  source_snapshot_id: "club-transfer-fixture",
  policy_id: "club-transfer-fixture",
  rules: {
    squad_size: 8,
    starting_size: 5,
    squad_position_limits: { GK: 2, DEF: 2, MID: 2, FWD: 2 },
    starting_position_min: { GK: 1, DEF: 0, MID: 0, FWD: 1 },
    starting_position_max: { GK: 1, DEF: 2, MID: 2, FWD: 2 },
    max_players_per_team: 3,
    max_free_transfers: 5,
    hit_cost_scaled: 400,
    hit_points_charged: 4,
    expected_points_scale: 100,
  },
  players: positions.flatMap((position, index) =>
    Array.from({ length: 4 }, (_, offset) => {
      const id = index * 4 + offset + 1;
      const points = offset < 2 ? 10 : 1;
      return {
        id,
        name: String(id),
        short_name: String(id),
        position,
        team: offset === 0 ? "Excess" : `Club ${id}`,
        buy_tenths: 50,
        expected_points: points,
        coefficients: [points * 10, points * 90, points * 100] as [number, number, number],
      };
    }),
  ),
};
const entry: DevicePlanEntry = {
  held: [1, 2, 5, 6, 9, 10, 13, 14],
  bank_tenths: 100,
  free_transfers: 3,
  sell_tenths: {},
};
const clubCount = (ids: number[]) => ids.filter((id) => [1, 5, 9, 13].includes(id)).length;

describe("holding an excess club after a real club transfer", () => {
  it("keeps the stronger held squad instead of forcing a needless sale", () => {
    const answer = solvePlan(solver, document, entry, () => 0);
    expect(answer.transfers_in).toEqual([]);
    expect(clubCount(answer.squad)).toBe(4);
    expect(whatIfAccount(document, entry, answer.squad).breaks).toEqual([]);
  });

  it("can explicitly roll under a zero transfer cap", () => {
    const answer = solveWeek(solver, document, entry, { transferCap: 0 });
    expect(answer?.squad).toEqual(entry.held);
  });

  it.each([null, "wildcard", "freehit"] as const)(
    "restores every club's limit on a transfer under %s",
    (chip: DeviceChip | null) => {
      const problem = memberWeekProblem(document, entry, { chip });
      // An unrelated purchase cannot leave all four excess holdings intact.
      for (const id of [1, 3, 5, 9, 13])
        problem.rows.push(row(`hold_${id}`, [term(1, `s${id - 1}`)], "=", 1));
      expect(solver.solve(lpText(problem), EXACT).Status).toBe("Infeasible");
      const corrected = memberWeekProblem(document, entry, { chip });
      corrected.rows.push(row("buy", [term(1, "s2")], "=", 1));
      expect(solver.solve(lpText(corrected), EXACT).Status).toBe("Optimal");
    },
  );

  it("the what-if account applies the strict limit to an unrelated free transfer", () => {
    const changed = entry.held.map((id) => (id === 2 ? 3 : id));
    expect(whatIfAccount(document, entry, changed)).toMatchObject({
      transfers: 1,
      hitPoints: 0,
      breaks: [{ rule: "club", team: "Excess", count: 4, limit: 3 }],
    });
    expect(
      whatIfAccount(
        document,
        entry,
        entry.held.map((id) => (id === 1 ? 3 : id)),
      ).breaks,
    ).toEqual([]);
  });
});
