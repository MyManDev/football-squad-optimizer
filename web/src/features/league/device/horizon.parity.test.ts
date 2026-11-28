/** H3/H5 parity is on the unchanged server objective, with independently certified moves. */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { beforeAll, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/horizons.json";
import { horizonInputs, horizonProblem, horizonVariable } from "./lp/horizon";
import { EXACT, lpText, row, term, type LpSolver } from "./lp/problem";
import { checkedColumns } from "./priorityWitness";
import { solveHorizon } from "./solve/horizon";
import { DevicePlanRefused } from "./solve/week";
import type { DevicePlanDocument, DevicePlanEntry } from "./types";

const require = createRequire(import.meta.url);
let solver: LpSolver;
beforeAll(async () => {
  const load = (await import("highs")).default;
  solver = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);

const document = fixture.document as unknown as DevicePlanDocument;
const cases = fixture.members.flatMap((member) =>
  ([3, 5] as const).map((window) => ({
    member,
    window,
    reference: member.reference[String(window) as "3" | "5"],
  })),
);

describe.each(cases)("member $member.entry_id, H$window", ({ member, window, reference }) => {
  it("has the server objective within 1e-6 and certified unique moves", () => {
    const answer = solveHorizon(solver, document, member.entry, window);
    const full = solveHorizon(solver, document, member.entry, window, undefined, "full");
    expect(Math.abs(answer.objective - full.objective)).toBeLessThanOrEqual(1e-6);
    expect(answer.objective_scaled).toBe(full.objective_scaled);
    expect(Math.abs(answer.objective - reference.objective)).toBeLessThanOrEqual(1e-6);
    expect(answer.objective_scaled).toBe(reference.objective_scaled);
    expect(answer.plan_weeks).toHaveLength(window);
    if (reference.unique_moves) {
      for (const [w, week] of answer.plan_weeks.entries()) {
        const expected = reference.weeks[w]!;
        expect(week.transfers_in).toEqual(expected.transfers_in);
        expect(week.transfers_out).toEqual(expected.transfers_out);
        expect(week.transfers_in).toEqual(full.plan_weeks[w]!.transfers_in);
        expect(week.transfers_out).toEqual(full.plan_weeks[w]!.transfers_out);
        expect(week.bank_after_tenths).toBe(expected.bank_after_tenths);
        expect(week.free_transfers_before).toBe(expected.free_transfers_before);
        expect(week.free_transfers_after).toBe(expected.free_transfers_after);
        expect(week.transfer_hit_points).toBe(expected.transfer_hit_points);
      }
    }
    // The server proves these tiers independently of move uniqueness. Equal tier
    // values can still permit several equivalent squads or lineups.
    const rank = new Map(document.players.map((player, index) => [player.id, index]));
    const tiers = (weeks: Array<{ squad: number[]; starting_xi: number[]; captain: number }>) => [
      weeks.reduce((sum, week) => sum + rank.get(week.captain)!, 0),
      weeks.reduce(
        (sum, week) => sum + week.starting_xi.reduce((part, id) => part + rank.get(id)!, 0),
        0,
      ),
      weeks.reduce(
        (sum, week) => sum + week.squad.reduce((part, id) => part + rank.get(id)!, 0),
        0,
      ),
    ];
    expect(tiers(answer.plan_weeks)).toEqual(tiers(full.plan_weeks));
    if (reference.tiebreak_completed) {
      expect(tiers(answer.plan_weeks)).toEqual(tiers(reference.weeks));
    }
  }, 60_000);
});

it("uses a new sale lot after an original holding is sold and repurchased", () => {
  const entry = fixture.members[0]!.entry;
  const problem = horizonProblem(document, entry, 3);
  const leaving = document.players.findIndex((player) => player.id === 1012);
  const arriving = document.players.findIndex((player) => player.id === 1019);
  for (let w = 0; w < 3; w += 1) {
    problem.rows.push(
      row(
        `force_in_${w}`,
        [term(1, horizonVariable("i", w, w === 1 ? leaving : arriving))],
        "=",
        1,
      ),
    );
    problem.rows.push(
      row(
        `force_out_${w}`,
        [term(1, horizonVariable("o", w, w === 1 ? arriving : leaving))],
        "=",
        1,
      ),
    );
  }
  const answer = solver.solve(lpText(problem), EXACT);
  expect(answer.Status).toBe("Optimal");
  expect(checkedColumns(problem, answer)).not.toBeNull();
  const buy = (id: number) => document.players.find((player) => player.id === id)!.buy_tenths;
  const first = entry.bank_tenths + entry.sell_tenths["1012"] - buy(1019);
  const second = first + buy(1019) - buy(1012);
  const third = second + buy(1012) - buy(1019);
  expect([0, 1, 2].map((w) => answer.Columns[horizonVariable("b", w)]!.Primal)).toEqual([
    first,
    second,
    third,
  ]);
});

it("refuses missing, shifted or changing-price horizon inputs", () => {
  expect(() => horizonInputs({ ...document, horizon: undefined } as DevicePlanDocument, 3)).toThrow(
    DevicePlanRefused,
  );
  const shifted = structuredClone(fixture.document);
  shifted.horizon.weeks[1]!.gameweek += 1;
  expect(() => horizonInputs(shifted as unknown as DevicePlanDocument, 3)).toThrow(
    DevicePlanRefused,
  );
  const repriced = structuredClone(fixture.document);
  repriced.horizon.weeks[2]!.players[0]!.buy_tenths += 1;
  expect(() =>
    horizonProblem(
      repriced as unknown as DevicePlanDocument,
      fixture.members[0]!.entry as DevicePlanEntry,
      3,
    ),
  ).toThrow(DevicePlanRefused);
});
