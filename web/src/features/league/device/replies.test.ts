/**
 * What the worker posts for a request: one answer, as before, for every request but chip
 * gains; for chip gains the plain plan first, with its own solving time, and the gains
 * after it from the same run. A plain plan that is refused sends no gains, and a failure
 * after the plan loses the gains, never the plan.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { beforeAll, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import type { LpSolver } from "./lp/problem";
import { replyTo, type DevicePlanReply } from "./replies";
import type { DevicePlanRequest } from "./requests";
import { solvePlan } from "./solve/week";
import type { DeviceChip, DevicePlanDocument, DevicePlanEntry } from "./types";

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
const PLAIN: DevicePlanRequest = { id: 7, document, entry };
const GAINS: DevicePlanRequest = { ...PLAIN, chipGains: CHIPS };

/**
 * HiGHS on a clock that moves one second for each solve, so a reply's seconds count the
 * solves it waited for. `broken` names the calls that throw, `stopped` those that reach
 * the ceiling.
 */
function clocked({
  broken = () => false,
  stopped = () => false,
}: { broken?: (call: number) => boolean; stopped?: (call: number) => boolean } = {}) {
  let calls = 0;
  const solver: LpSolver = {
    solve(problem, options) {
      const call = calls++;
      if (broken(call)) throw new Error("the solver broke");
      const result = highs.solve(problem, options);
      return stopped(call) ? { ...result, Status: "Time limit reached" } : result;
    },
  };
  return { solver, now: () => calls * 1000, calls: () => calls };
}

function replies(request: DevicePlanRequest, setup = clocked()): DevicePlanReply[] {
  const posted: DevicePlanReply[] = [];
  replyTo(setup.solver, request, (reply) => posted.push(reply), setup.now);
  return posted;
}

function plainSolves(): number {
  const setup = clocked();
  solvePlan(setup.solver, document, entry, setup.now);
  return setup.calls();
}

describe("the worker's replies", () => {
  it("answer a request without chip gains once, as before", () => {
    const posted = replies(PLAIN);
    expect(posted.map((reply) => reply.kind)).toEqual(["answer"]);
  });

  it("post the plain plan before the gains, and the plan is the plain plan alone", () => {
    const setup = clocked();
    const posted: DevicePlanReply[] = [];
    const solvesAtPost: number[] = [];
    replyTo(
      setup.solver,
      GAINS,
      (reply) => {
        posted.push(reply);
        solvesAtPost.push(setup.calls());
      },
      setup.now,
    );
    // The plan is posted as soon as the plain plan is solved, before any chip's solve.
    expect(solvesAtPost[0]).toBe(plainSolves());
    expect(posted.map((reply) => [reply.id, reply.kind])).toEqual([
      [7, "plan"],
      [7, "gains"],
    ]);
    const [plan, gains] = posted;
    const [alone] = replies(PLAIN);
    if (plan?.kind !== "plan" || gains?.kind !== "gains" || alone?.kind !== "answer") {
      throw new Error("The replies are not a plan, its gains and a plain answer.");
    }
    // The plan carries the plain plan's own solving time, as the plain request's answer
    // does; the gains carry the whole run's.
    expect(plan.answer).toEqual(alone.answer);
    expect(plan.answer.seconds).toBe(plainSolves());
    expect(gains.seconds).toBeGreaterThan(plan.answer.seconds);
    expect(Object.keys(gains.gains!)).toEqual(CHIPS);
  });

  it("send no gains when the plain plan is refused", () => {
    const posted = replies(GAINS, clocked({ stopped: () => true }));
    expect(posted.map((reply) => reply.kind)).toEqual(["refused"]);
  });

  it("send no gains when the plain plan fails", () => {
    const posted = replies(GAINS, clocked({ broken: () => true }));
    expect(posted.map((reply) => reply.kind)).toEqual(["failed"]);
  });

  it("read a chip the ceiling stops as unknown, never zero", () => {
    const plain = plainSolves();
    const posted = replies(GAINS, clocked({ stopped: (call) => call >= plain }));
    expect(posted.at(-1)).toMatchObject({
      kind: "gains",
      gains: { wildcard: null, freehit: null, bboost: null, "3xc": null },
    });
  });

  it("keep the plan when a chip solve breaks, and send no gains for it", () => {
    const plain = plainSolves();
    const posted = replies(GAINS, clocked({ broken: (call) => call === plain }));
    expect(posted.map((reply) => reply.kind)).toEqual(["plan", "gains"]);
    expect(posted[1]).toMatchObject({ kind: "gains", gains: null });
  });
});
