/**
 * The what-if arithmetic (#1132) on the synthetic device capture
 * (`synthetic-device-plan-fixture`), member 1: its advised fifteen is the reference plan
 * (152 out, 160 in), so the numbers here are the device's own. Taking the transfer back
 * must read the held fifteen exactly as the device's hold problem did, and every rule a
 * hand-made fifteen breaks is the row of the one-week problem that says so.
 */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { beforeAll, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import type { LpSolver } from "./lp/problem";
import type { DevicePlanDocument, DevicePlanEntry } from "./types";
import { whatIfAccount, whatIfDocument, whatIfValues } from "./whatIf";

const require = createRequire(import.meta.url);
let solver: LpSolver;
beforeAll(async () => {
  const load = (await import("highs")).default;
  solver = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);

const document = whatIfDocument(fixture.document as unknown as DevicePlanDocument);
const member = fixture.members[0]!;
const entry = member.entry as unknown as DevicePlanEntry;
const ADVISED = member.reference.squad;

const swapped = (out: number, into: number) => ADVISED.map((id) => (id === out ? into : id));

describe("the advised fifteen", () => {
  it("reads as the plan the device proved: its points, one transfer, no hit, nothing broken", () => {
    expect(whatIfValues(solver, document, [ADVISED])[0]).toBeCloseTo(
      member.reference.expected_own_points,
      9,
    );
    // 152 sold for 6.6, 160 bought for 5.9, from an empty bank.
    expect(whatIfAccount(document, entry, ADVISED)).toEqual({
      bankTenths: 7,
      transfers: 1,
      hitPoints: 0,
      breaks: [],
    });
  });
});

describe("one swap", () => {
  it("taking 160 back for 152 reads the held fifteen as the device's hold problem did", () => {
    const back = swapped(160, 152);
    const [advised, held] = whatIfValues(solver, document, [ADVISED, back]);
    expect(held).toBeCloseTo(member.reference.hold_points, 9);
    // The difference to the advice is the plan's gain over holding, turned.
    expect(held! - advised!).toBeCloseTo(-member.reference.expected_gain_vs_hold, 9);
    expect(whatIfAccount(document, entry, back)).toEqual({
      bankTenths: 0,
      transfers: 0,
      hitPoints: 0,
      breaks: [],
    });
  });

  it("a second transfer past the free one is charged at the game's hit", () => {
    // 145 (Club 4) out for 143 (Club 4): 8.6 back, 5.9 spent.
    expect(whatIfAccount(document, entry, swapped(145, 143))).toEqual({
      bankTenths: 34,
      transfers: 2,
      hitPoints: 4,
      breaks: [],
    });
  });
});

describe("the rules a hand-made fifteen breaks", () => {
  it("a fourth player of one club breaks the club limit", () => {
    // 147 is Club 3's, which already has 101, 137 and 148.
    expect(whatIfAccount(document, entry, swapped(145, 147)).breaks).toEqual([
      { rule: "club", team: "Club 3", count: 4, limit: 3 },
    ]);
  });

  it("a purchase past the bank breaks the budget by what it is short", () => {
    // 129 sold for 5.1 and 134 bought for 12.0, with 0.7 in the bank: 6.2 short.
    const account = whatIfAccount(document, entry, swapped(129, 134));
    expect(account.bankTenths).toBe(-62);
    expect(account.breaks).toEqual([{ rule: "budget", shortTenths: 62 }]);
  });

  it("a removed player leaves the squad short and the position under its quota", () => {
    const fourteen = ADVISED.filter((id) => id !== 148);
    expect(whatIfAccount(document, entry, fourteen).breaks).toEqual([
      { rule: "size", count: 14, size: 15 },
      { rule: "position", position: "MID", count: 4, required: 5 },
    ]);
    // An eleven can still be fielded from the fourteen, so its points are still read.
    expect(whatIfValues(solver, document, [fourteen])[0]).not.toBeNull();
  });

  it("a fifteen no eleven can be fielded from has no points", () => {
    const noKeeper = ADVISED.filter((id) => id !== 101 && id !== 107);
    expect(whatIfValues(solver, document, [noKeeper])).toEqual([null]);
  });
});
