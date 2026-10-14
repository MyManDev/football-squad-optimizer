/**
 * #981 step 3: every solve of one request shares the device's ceiling, given to HiGHS as
 * what is left of it; a solve the clock stops is refused, never shown, as the server
 * refuses a plan its own ceiling cut short.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { beforeAll, describe, expect, it } from "vitest";

import fixture from "../../../../fixtures/device-plan/instances.json";
import type { LpSolver } from "../lp/problem";
import type { DevicePlanDocument, DevicePlanEntry } from "../types";
import { DEVICE_SOLVE_CEILING_SECONDS, withinCeiling } from "./ceiling";
import { DevicePlanRefused, solvePlan } from "./week";

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

/** A solver that records the options each solve was given and answers as told. */
function recording(status: string, inner?: LpSolver) {
  const given: Record<string, unknown>[] = [];
  const solver: LpSolver = {
    solve(problem, options = {}) {
      given.push(options);
      if (inner) return inner.solve(problem, options);
      return { Status: status, ObjectiveValue: 0, Columns: {} };
    },
  };
  return { solver, given };
}

describe("the device's ceiling", () => {
  it("gives each solve what is left of it, and a spent ceiling the least time", () => {
    let clock = 0;
    const { solver, given } = recording("Optimal");
    const bounded = withinCeiling(solver, 10, () => clock);
    bounded.solve("a", { mip_rel_gap: 0 });
    clock = 4_000;
    bounded.solve("b");
    clock = 12_000;
    bounded.solve("c");
    expect(given.map((options) => options.time_limit)).toEqual([10, 6, 0.001]);
    // The solve's own options are kept beside the time.
    expect(given[0]!.mip_rel_gap).toBe(0);
  });

  it("starts its clock when it is made, after the solver has loaded", () => {
    let clock = 50_000;
    const { solver, given } = recording("Optimal");
    const bounded = withinCeiling(solver, 10, () => clock);
    clock = 51_000;
    bounded.solve("a");
    expect(given[0]!.time_limit).toBe(9);
  });

  it("refuses a plan whose solve the clock stopped, and shows nothing", () => {
    const { solver } = recording("Time limit reached");
    expect(() => solvePlan(withinCeiling(solver), document, entry, () => 0)).toThrow(
      DevicePlanRefused,
    );
    try {
      solvePlan(withinCeiling(solver), document, entry, () => 0);
    } catch (error) {
      expect((error as DevicePlanRefused).status).toBe("Time limit reached");
      expect((error as DevicePlanRefused).stage).toBe("plan");
    }
  });

  it("changes no answer the solver proves within it", () => {
    const { solver, given } = recording("", highs);
    const bounded = solvePlan(withinCeiling(solver), document, entry, () => 0);
    const plain = solvePlan(highs, document, entry, () => 0);
    expect(bounded).toEqual(plain);
    expect(given.length).toBeGreaterThan(1);
    for (const options of given) {
      expect(options.time_limit).toBeGreaterThan(0);
      expect(options.time_limit).toBeLessThanOrEqual(DEVICE_SOLVE_CEILING_SECONDS);
    }
  });
});
