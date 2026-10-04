/**
 * The device solver returns the server's answer. Every instance in the fixture was solved
 * by the repository's planner (scripts/export_device_plan_fixture.py); the Python side
 * holds the recorded answers to the planner, and this side holds the device solver to
 * the recorded answers. A drift between the two models fails here.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { beforeAll, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import { memberWeekProblem } from "./lp/memberWeek";
import { lpText, type LpSolver } from "./lp/problem";
import { solveRequest } from "./requests";
import { DevicePlanRefused, solvePlan } from "./solve/week";
import {
  isDevicePlanDocument,
  isDevicePlanEntry,
  type DeviceChip,
  type DevicePlanDocument,
  type DevicePlanEntry,
} from "./types";

const require = createRequire(import.meta.url);

let solver: LpSolver;
beforeAll(async () => {
  // The wasm binary is read from the package itself: the test runs in Node, where the
  // loader's own URL resolution is not what the page uses.
  const wasm = readFileSync(require.resolve("highs/runtime"));
  const load = (await import("highs")).default;
  solver = (await load({ wasmBinary: wasm })) as unknown as LpSolver;
}, 60_000);

const document = fixture.document as unknown as DevicePlanDocument;
// The JSON module's literal types are one instance's keys; the shapes are checked below.
const members = fixture.members.map((member) => ({
  ...member,
  entry: member.entry as unknown as DevicePlanEntry,
}));

describe("the fixture", () => {
  it("is the two published shapes", () => {
    expect(isDevicePlanDocument(document)).toBe(true);
    for (const member of members) expect(isDevicePlanEntry(member.entry)).toBe(true);
    expect(members.length).toBeGreaterThanOrEqual(8);
    // At least one instance pays for a transfer, so the hit path is held too.
    expect(members.some((m) => m.reference.transfer_hit_points > 0)).toBe(true);
  });
});

describe.each(members.map((member) => [member.entry_id, member] as const))(
  "instance %i",
  (_, member) => {
    it("solves to the server's squad, eleven, captain, vice, bench, transfers and points", () => {
      const answer = solvePlan(solver, document, member.entry, () => 0);
      const reference = member.reference;
      expect(answer.squad).toEqual(reference.squad);
      expect(answer.starting_xi).toEqual(reference.starting_xi);
      expect(answer.captain).toBe(reference.captain);
      expect(answer.vice_captain).toBe(reference.vice_captain);
      expect(answer.bench).toEqual(reference.bench);
      expect(answer.transfers_in).toEqual(reference.transfers_in);
      expect(answer.transfers_out).toEqual(reference.transfers_out);
      expect(answer.transfer_hit_points).toBe(reference.transfer_hit_points);
      expect(answer.expected_own_points).toBeCloseTo(reference.expected_own_points, 9);
      expect(answer.hold_points).toBeCloseTo(reference.hold_points, 9);
      // The move rows: the same pairs, and each row's gain as the advice attributes it.
      expect(answer.moves.map((m) => [m.out, m.in])).toEqual(
        reference.moves.map((m) => [m.out, m.in]),
      );
      for (const [index, move] of answer.moves.entries()) {
        const expected = reference.moves[index]!.gain;
        if (expected === null) expect(move.gain).toBeNull();
        else expect(move.gain).toBeCloseTo(expected, 9);
      }
      if (reference.expected_gain_vs_hold === null) expect(answer.expected_gain_vs_hold).toBeNull();
      else expect(answer.expected_gain_vs_hold).toBeCloseTo(reference.expected_gain_vs_hold, 9);
      // The planner reports its objective unscaled; the device's integer divided by the
      // scale is that number.
      expect(answer.objective).toBeCloseTo(reference.objective_value, 6);
    });
  },
);

describe("the model text", () => {
  it("states every rule once and nothing it was not given", () => {
    const lp = lpText(memberWeekProblem(document, members[0]!.entry));
    const rules = document.rules;
    expect(lp).toContain(`squad: `);
    expect(lp).toContain(` = ${rules.squad_size}`);
    expect(lp).toContain(`xi: `);
    expect(lp).toContain(`cap: `);
    for (const position of Object.keys(rules.squad_position_limits)) {
      expect(lp).toContain(`sq_${position}:`);
      expect(lp).toContain(`lo_${position}:`);
      expect(lp).toContain(`hi_${position}:`);
    }
    expect(lp).toContain(`- ${rules.hit_cost_scaled} paid`);
    expect(lp).toContain(`>= ${-members[0]!.entry.free_transfers}`);
    expect((lp.match(/club\d+:/g) ?? []).length).toBe(
      new Set(document.players.map((p) => p.team)).size,
    );
  });

  it("refuses rather than shows a plan it could not prove", () => {
    const starved = { ...members[0]!.entry, bank_tenths: -100_000 };
    expect(() => solvePlan(solver, document, starved, () => 0)).toThrow(DevicePlanRefused);
  });
});

// The chip instances: each chip the game has, forced for the week on two of the fifteens,
// solved by the planner with every total on the chip week's basis.
const chipCases = fixture.chips.map((c) => ({
  ...c,
  entry: members.find((m) => m.entry_id === c.entry_id)!.entry,
  chip: c.chip as DeviceChip,
}));

describe("the chip instances", () => {
  it("play every chip on the two fifteens", () => {
    expect(new Set(chipCases.map((c) => c.chip))).toEqual(
      new Set(["wildcard", "freehit", "bboost", "3xc"]),
    );
    expect(chipCases.length).toBe(8);
  });
});

describe.each(chipCases.map((c) => [`${c.entry_id} ${c.chip}`, c] as const))(
  "chip instance %s",
  (_, c) => {
    it("solves to the server's chip week and its gain against the plain plan", () => {
      const answer = solveRequest(solver, { document, entry: c.entry, chip: c.chip });
      const reference = c.reference;
      expect(answer.chip).toBe(c.chip);
      expect(answer.squad).toEqual(reference.squad);
      expect(answer.starting_xi).toEqual(reference.starting_xi);
      expect(answer.captain).toBe(reference.captain);
      expect(answer.vice_captain).toBe(reference.vice_captain);
      expect(answer.bench).toEqual(reference.bench);
      expect(answer.transfers_in).toEqual(reference.transfers_in);
      expect(answer.transfers_out).toEqual(reference.transfers_out);
      expect(answer.transfer_hit_points).toBe(reference.transfer_hit_points);
      expect(answer.expected_own_points).toBeCloseTo(reference.expected_own_points, 9);
      expect(answer.hold_points).toBeCloseTo(reference.hold_points, 9);
      expect(answer.moves.map((m) => [m.out, m.in])).toEqual(
        reference.moves.map((m) => [m.out, m.in]),
      );
      for (const [index, move] of answer.moves.entries()) {
        const expected = reference.moves[index]!.gain;
        if (expected === null) expect(move.gain).toBeNull();
        else expect(move.gain).toBeCloseTo(expected, 9);
      }
      if (reference.expected_gain_vs_hold === null) expect(answer.expected_gain_vs_hold).toBeNull();
      else expect(answer.expected_gain_vs_hold).toBeCloseTo(reference.expected_gain_vs_hold, 9);
      expect(answer.gain_vs_no_chip).toBeCloseTo(reference.gain_vs_no_chip, 9);
    });
  },
);
