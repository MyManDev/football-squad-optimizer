/**
 * The device's Top 100 influence is the advice service's. The fixture's rival world
 * carries each player's weighted points on the integer scale as the producer writes
 * them, and four cases answered by `advise_with_top100` itself; the device chooses on
 * those integers and states everything on the base points, and must say what the service
 * said, the price and each row's reason included.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { beforeAll, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import type { LpSolver } from "./lp/problem";
import { solveRequest } from "./requests";
import { DevicePlanRefused } from "./solve/week";
import { benchCoefficient } from "./strategies/top100";
import { isDevicePlanDocument, type DevicePlanDocument, type DevicePlanEntry } from "./types";

const require = createRequire(import.meta.url);

let solver: LpSolver;
beforeAll(async () => {
  const wasm = readFileSync(require.resolve("highs/runtime"));
  const load = (await import("highs")).default;
  solver = (await load({ wasmBinary: wasm })) as unknown as LpSolver;
}, 60_000);

const world = fixture.rivals;
const document = world.document as unknown as DevicePlanDocument;
const members = world.members as unknown as Record<string, DevicePlanEntry>;

describe("the Top 100 inputs", () => {
  it("are on every player, for every weight the rules offer", () => {
    expect(isDevicePlanDocument(document)).toBe(true);
    const weights = document.rules.top100!.weights.map(String);
    for (const player of document.players) {
      expect(typeof player.top100_count).toBe("number");
      expect(Object.keys(player.top100_scaled!).sort()).toEqual([...weights].sort());
      // Unbacked players keep their base points at every weight.
      if (player.top100_count === 0) {
        for (const weight of weights) {
          expect(player.top100_scaled![weight]).toBe(player.coefficients[2]);
        }
      }
    }
    // The bench rule from the integer is the server's: the base coefficients agree.
    for (const player of document.players) {
      expect(benchCoefficient(player.coefficients[2])).toBe(player.coefficients[0]);
    }
    // One case moves a decision, so the price path is exercised.
    expect(world.top100_cases.some((c) => c.reference.changed)).toBe(true);
  });
});

describe("a weight combines with nothing", () => {
  it("is refused beside a chip or a rival strategy, and where the document lacks it", () => {
    const entry = members["101"]!;
    expect(() =>
      solveRequest(solver, { document, entry, top100Weight: 20, chip: "3xc" }, () => 0),
    ).toThrow(DevicePlanRefused);
    expect(() =>
      solveRequest(
        solver,
        {
          document,
          entry,
          top100Weight: 20,
          strategy: { name: "fark-yarat", rival: world.rivals["202"] as never },
        },
        () => 0,
      ),
    ).toThrow(DevicePlanRefused);
    expect(() => solveRequest(solver, { document, entry, top100Weight: 15 }, () => 0)).toThrow(
      DevicePlanRefused,
    );
  });
});

describe.each(world.top100_cases.map((c) => [`${c.entry_id} at ${c.weight}`, c] as const))(
  "Top 100 case %s",
  (_, c) => {
    it("is the service's plan on base points, with its price and its reasons", () => {
      const answer = solveRequest(
        solver,
        { document, entry: members[String(c.entry_id)]!, top100Weight: c.weight },
        () => 0,
      );
      const reference = c.reference;
      expect(answer.starting_xi).toEqual(reference.starting_xi);
      expect(answer.captain).toBe(reference.captain);
      expect(answer.vice_captain).toBe(reference.vice_captain);
      expect(answer.bench).toEqual(reference.bench);
      expect(answer.transfers_in).toEqual(reference.transfers_in);
      expect(answer.transfers_out).toEqual(reference.transfers_out);
      expect(answer.transfer_hit_points).toBe(reference.transfer_hit_points);
      expect(answer.expected_own_points).toBeCloseTo(reference.expected_own_points, 9);
      expect(answer.moves.map((m) => [m.out, m.in])).toEqual(
        reference.moves.map((m) => [m.out, m.in]),
      );
      for (const [index, move] of answer.moves.entries()) {
        const expected = reference.moves[index]!.gain;
        if (expected === null) expect(move.gain).toBeNull();
        else expect(move.gain).toBeCloseTo(expected, 9);
        expect(answer.top100!.reasons[index]).toBe(reference.moves[index]!.reason);
      }
      if (reference.expected_gain_vs_hold === null) expect(answer.expected_gain_vs_hold).toBeNull();
      else expect(answer.expected_gain_vs_hold).toBeCloseTo(reference.expected_gain_vs_hold, 9);
      expect(answer.top100!.weight).toBe(c.weight);
      expect(answer.top100!.changed).toBe(reference.changed);
      expect(answer.top100!.expected_points_cost).toBeCloseTo(reference.expected_points_cost, 9);
      expect(answer.top100!.expected_points_cost_ceiling).toBeCloseTo(
        reference.expected_points_cost_ceiling!,
        9,
      );
    });
  },
);
