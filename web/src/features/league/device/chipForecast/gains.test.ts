import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { beforeAll, describe, expect, it } from "vitest";

import fixture from "../../../../fixtures/device-plan/instances.json";
import type { LpSolver } from "../lp/problem";
import { solveRequest } from "../requests";
import { DevicePlanRefused, solvePlan } from "../solve/week";
import type { DeviceChip, DevicePlanDocument, DevicePlanEntry } from "../types";

const require = createRequire(import.meta.url);
let highs: LpSolver;

beforeAll(async () => {
  const load = (await import("highs")).default;
  highs = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);

const document = fixture.document as unknown as DevicePlanDocument;
const entry = fixture.members[1]!.entry as unknown as DevicePlanEntry;
const CHIPS: DeviceChip[] = ["wildcard", "freehit", "bboost", "3xc"];
const clock = () => 0;

/** HiGHS, counting its solves, and reporting a time limit for the solves `stopped` names. */
function counting(stopped: (call: number) => boolean = () => false) {
  let calls = 0;
  const solver: LpSolver = {
    solve(problem, options) {
      const call = calls++;
      const result = highs.solve(problem, options);
      return stopped(call) ? { ...result, Status: "Time limit reached" } : result;
    },
  };
  return { solver, calls: () => calls };
}

/** How many solver calls one plan takes, plain or with a chip. */
function cost(chip: DeviceChip | null): number {
  const { solver, calls } = counting();
  solvePlan(solver, document, entry, clock, chip);
  return calls();
}

describe("the chip gains request", () => {
  it("solves the plain plan once and each held chip once: 1 + n plans, not 2n", () => {
    const { solver, calls } = counting();
    const answer = solveRequest(solver, { document, entry, chipGains: CHIPS }, clock);
    const plain = cost(null);
    expect(calls()).toBe(plain + CHIPS.reduce((sum, chip) => sum + cost(chip), 0));
    // The answer is the plain plan itself, with the gains beside it.
    const alone = solvePlan(highs, document, entry, clock);
    expect({ ...answer, chip_gains: undefined }).toEqual({ ...alone, chip_gains: undefined });
    expect(answer.chip).toBeNull();
  });

  it("gives each chip the gain a chip request gives it", () => {
    const answer = solveRequest(highs, { document, entry, chipGains: CHIPS }, clock);
    expect(Object.keys(answer.chip_gains!)).toEqual(CHIPS);
    for (const chip of CHIPS) {
      const single = solveRequest(highs, { document, entry, chip }, clock);
      expect(answer.chip_gains![chip]).toBeCloseTo(single.gain_vs_no_chip!, 9);
    }
  });

  it("asks each chip once, in the game's order, whatever the request repeats", () => {
    const { solver, calls } = counting();
    const answer = solveRequest(
      solver,
      { document, entry, chipGains: ["3xc", "wildcard", "3xc"] },
      clock,
    );
    expect(Object.keys(answer.chip_gains!)).toEqual(["wildcard", "3xc"]);
    expect(calls()).toBe(cost(null) + cost("wildcard") + cost("3xc"));
  });

  it("reads a refused chip solve as an unknown gain, never zero, and keeps the plan", () => {
    const plain = cost(null);
    const wildcard = cost("wildcard");
    // The Free Hit's first solve stops at the ceiling; every other solve is proved.
    const { solver } = counting((call) => call === plain + wildcard);
    const answer = solveRequest(solver, { document, entry, chipGains: CHIPS }, clock);
    expect(answer.chip_gains!.freehit).toBeNull();
    for (const chip of ["wildcard", "bboost", "3xc"] as const) {
      expect(typeof answer.chip_gains![chip]).toBe("number");
    }
    expect(answer.squad).toEqual(solvePlan(highs, document, entry, clock).squad);
  });

  it("reads every chip as unknown when the ceiling is spent after the plain plan", () => {
    const plain = cost(null);
    const { solver } = counting((call) => call >= plain);
    const answer = solveRequest(solver, { document, entry, chipGains: CHIPS }, clock);
    expect(answer.chip_gains).toEqual({ wildcard: null, freehit: null, bboost: null, "3xc": null });
  });

  it("refuses the whole request when the plain plan itself is not proved", () => {
    const { solver } = counting(() => true);
    expect(() => solveRequest(solver, { document, entry, chipGains: CHIPS }, clock)).toThrow(
      DevicePlanRefused,
    );
  });

  it("passes on a failure that is not a refusal", () => {
    const plain = cost(null);
    const solver: LpSolver = {
      solve: (() => {
        let calls = 0;
        return (problem: string, options?: Record<string, unknown>) => {
          if (calls++ === plain) throw new Error("the solver broke");
          return highs.solve(problem, options);
        };
      })(),
    };
    expect(() => solveRequest(solver, { document, entry, chipGains: CHIPS }, clock)).toThrow(
      "the solver broke",
    );
  });

  it.each([
    ["a chip", { chip: "bboost" as const }],
    ["a weight", { top100Weight: 10 }],
    [
      "a rival strategy",
      {
        strategy: {
          name: "ortak-koru" as const,
          rival: { entry_id: 1, starting_xi: [], captain: 0 },
        },
      },
    ],
  ])("combines with nothing: not with %s", (_, extra) => {
    expect(() =>
      solveRequest(highs, { document, entry, chipGains: CHIPS, ...extra }, clock),
    ).toThrow(DevicePlanRefused);
  });

  it("is the plain plan alone when no chip is held", () => {
    const answer = solveRequest(highs, { document, entry, chipGains: [] }, clock);
    expect(answer.chip_gains).toBeUndefined();
  });
});
