/**
 * The device's rival strategies are the advice service's. The fixture's `rivals` block is
 * the unit tests' world: its device document written by the real producer, its members'
 * blocks likewise, and every case answered by `advise_entry` itself under each rival
 * strategy against each rival (scripts/export_device_plan_fixture.py). The Python drift
 * guard holds those answers to the service; this holds the device to them, including the
 * case the service refuses.
 */

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { beforeAll, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import type { LpSolver } from "./lp/problem";
import { solveRequest } from "./requests";
import { DevicePlanRefused } from "./solve/week";
import { CATALOGUE_BANDS } from "./strategies/rival";
import {
  isDevicePlanDocument,
  isDevicePlanEntry,
  isRivalStrategy,
  type DevicePlanDocument,
  type DevicePlanEntry,
  type DeviceRival,
} from "./types";

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
const rivals = world.rivals as unknown as Record<string, DeviceRival>;

describe("the rival world", () => {
  it("is the producer's document and blocks, with the catalogue's bands", () => {
    expect(isDevicePlanDocument(document)).toBe(true);
    for (const entry of Object.values(members)) expect(isDevicePlanEntry(entry)).toBe(true);
    // The producer writes the bands from the catalogue; the device's own table must agree.
    expect(document.rules.strategies).toEqual(CATALOGUE_BANDS);
    expect(document.rules.hit_charged_scaled).toBe(
      Math.round(document.rules.hit_points_charged * document.rules.expected_points_scale),
    );
    // Both decisions and a refusal are among the cases, so the whole rule is exercised.
    const kinds = new Set(
      world.cases.map((c) => (c.reference.refused ? "refused" : c.reference.plan_kind)),
    );
    expect(kinds).toEqual(new Set(["within_free_transfers", "with_hits", "refused"]));
  });
});

describe.each(
  world.cases.map((c) => [`${c.entry_id} vs ${c.rival_entry_id} ${c.strategy}`, c] as const),
)("rival case %s", (_, c) => {
  it("is the service's plan, price, labels and alternative, or its refusal", () => {
    if (!isRivalStrategy(c.strategy)) throw new Error(`not a rival strategy: ${c.strategy}`);
    const request = {
      document,
      entry: members[String(c.entry_id)]!,
      strategy: { name: c.strategy, rival: rivals[String(c.rival_entry_id)]! },
    };
    const reference = c.reference;
    if (reference.refused) {
      expect(() => solveRequest(solver, request, () => 0)).toThrow(DevicePlanRefused);
      return;
    }
    const answer = solveRequest(solver, request, () => 0);
    expect(answer.starting_xi).toEqual(reference.starting_xi);
    expect(answer.captain).toBe(reference.captain);
    expect(answer.vice_captain).toBe(reference.vice_captain);
    expect(answer.bench).toEqual(reference.bench);
    expect(answer.transfers_in).toEqual(reference.transfers_in);
    expect(answer.transfers_out).toEqual(reference.transfers_out);
    expect(answer.transfer_hit_points).toBe(reference.transfer_hit_points);
    expect(answer.expected_own_points).toBeCloseTo(reference.expected_own_points!, 9);
    expect(answer.moves.map((m) => [m.out, m.in])).toEqual(
      reference.moves!.map((m) => [m.out, m.in]),
    );
    for (const [index, move] of answer.moves.entries()) {
      const expected = reference.moves![index]!.gain;
      if (expected === null) expect(move.gain).toBeNull();
      else expect(move.gain).toBeCloseTo(expected, 9);
    }
    if (reference.expected_gain_vs_hold === null) expect(answer.expected_gain_vs_hold).toBeNull();
    else expect(answer.expected_gain_vs_hold).toBeCloseTo(reference.expected_gain_vs_hold!, 9);
    const rival = answer.rival!;
    expect(rival.mode).toBe(c.strategy);
    expect(rival.rival_entry_id).toBe(c.rival_entry_id);
    expect(rival.expected_points_cost).toBeCloseTo(reference.expected_points_cost!, 9);
    expect(rival.expected_points_cost_ceiling).toBeCloseTo(
      reference.expected_points_cost_ceiling!,
      9,
    );
    expect(rival.overlap_count).toBe(reference.overlap_count);
    expect(rival.transfer_cap).toBe(reference.transfer_cap);
    expect(rival.overlap_target).toBe(reference.overlap_target);
    expect(rival.overlap_applied).toBe(reference.overlap_applied);
    expect(rival.plan_kind).toBe(reference.plan_kind);
    expect(rival.expected_gap_vs_rival).toBeCloseTo(reference.expected_gap_vs_rival!, 9);
    expect(rival.captain_agreement).toBe(reference.captain_agreement);
    const alternative = reference.alternative_plan;
    if (alternative === null || alternative === undefined) {
      expect(rival.alternative_plan).toBeNull();
    } else {
      expect(rival.alternative_plan).not.toBeNull();
      expect(rival.alternative_plan!.kind).toBe(alternative.kind);
      expect(rival.alternative_plan!.overlap_applied).toBe(alternative.overlap_applied);
      expect(rival.alternative_plan!.transfer_hit_points).toBe(alternative.transfer_hit_points);
      expect(rival.alternative_plan!.expected_points_cost).toBeCloseTo(
        alternative.expected_points_cost,
        9,
      );
      expect(rival.alternative_plan!.expected_points_cost_ceiling).toBeCloseTo(
        alternative.expected_points_cost_ceiling!,
        9,
      );
    }
  });
});
