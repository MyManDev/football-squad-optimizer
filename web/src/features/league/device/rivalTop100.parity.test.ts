/** Synthetic answers exported from advise_rival_with_top100, including refused bands. */
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

import { beforeAll, describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { deviceAdviceEnvelope } from "./deviceAdvice";
import type { LpSolver } from "./lp/problem";
import { solveRequest } from "./requests";
import { DevicePlanRefused } from "./solve/week";
import {
  isRivalStrategy,
  type DevicePlanDocument,
  type DevicePlanEntry,
  type DeviceRival,
} from "./types";

const require = createRequire(import.meta.url);
let solver: LpSolver;
beforeAll(async () => {
  const load = (await import("highs")).default;
  solver = (await load({
    wasmBinary: readFileSync(require.resolve("highs/runtime")),
  })) as unknown as LpSolver;
}, 60_000);

const world = fixture.rivals;
const document = world.document as unknown as DevicePlanDocument;
const members = world.members as unknown as Record<string, DevicePlanEntry>;
const rivals = world.rivals as unknown as Record<string, DeviceRival>;

describe.each(world.weighted_cases)("$entry_id vs $rival_entry_id, $strategy at $weight", (c) => {
  it("matches the server's decision, base points, prices and row reasons", () => {
    if (!isRivalStrategy(c.strategy)) throw new Error(c.strategy);
    const request = {
      document,
      entry: members[String(c.entry_id)]!,
      top100Weight: c.weight,
      strategy: { name: c.strategy, rival: rivals[String(c.rival_entry_id)]! },
    };
    const reference = c.reference;
    if (reference.refused) {
      expect(() => solveRequest(solver, request, () => 0)).toThrow(DevicePlanRefused);
      return;
    }
    const answer = solveRequest(solver, request, () => 0);
    for (const key of [
      "starting_xi",
      "bench",
      "captain",
      "vice_captain",
      "transfers_in",
      "transfers_out",
      "transfer_hit_points",
    ] as const) {
      expect(answer[key], key).toEqual(reference[key]);
    }
    expect(answer.expected_own_points).toBeCloseTo(reference.expected_own_points!, 9);
    if (reference.expected_gain_vs_hold === null) expect(answer.expected_gain_vs_hold).toBeNull();
    else expect(answer.expected_gain_vs_hold).toBeCloseTo(reference.expected_gain_vs_hold!, 9);
    expect(answer.moves.map((m) => [m.out, m.in])).toEqual(
      reference.moves!.map((m) => [m.out, m.in]),
    );
    for (const [index, move] of answer.moves.entries()) {
      const expected = reference.moves![index]!.gain;
      if (expected === null) expect(move.gain).toBeNull();
      else expect(move.gain).toBeCloseTo(expected, 9);
    }
    const band = answer.rival!;
    for (const key of [
      "overlap_count",
      "transfer_cap",
      "overlap_target",
      "overlap_applied",
      "plan_kind",
      "captain_agreement",
    ] as const) {
      expect(band[key], key).toEqual(reference[key]);
    }
    for (const key of [
      "expected_points_cost",
      "expected_points_cost_ceiling",
      "expected_gap_vs_rival",
    ] as const) {
      expect(band[key], key).toBeCloseTo(reference[key]!, 9);
    }
    if (reference.alternative_plan == null) expect(band.alternative_plan).toBeNull();
    else {
      expect(band.alternative_plan).toMatchObject({
        kind: reference.alternative_plan.kind,
        overlap_applied: reference.alternative_plan.overlap_applied,
        transfer_hit_points: reference.alternative_plan.transfer_hit_points,
      });
      expect(band.alternative_plan!.expected_points_cost).toBeCloseTo(
        reference.alternative_plan.expected_points_cost,
        9,
      );
      expect(band.alternative_plan!.expected_points_cost_ceiling).toBeCloseTo(
        reference.alternative_plan.expected_points_cost_ceiling!,
        9,
      );
    }
    expect(answer.top100!.weight).toBe(c.weight);
    expect(answer.top100!.changed).toBe(reference.changed);
    expect(answer.top100!.reasons).toEqual(reference.moves!.map((m) => m.reason));
    // The same payload consumed by the pitch keeps both the setting and the rival's account.
    const payload = deviceAdviceEnvelope(
      document,
      {
        entry: { ...mockEntrySquadEnvelopes[35249001]!.payload.entry, entry_id: c.entry_id },
        free_transfers_known: true,
        purchase_prices_known: true,
      },
      answer,
      new Date("2026-10-21T00:00:00Z"),
      352490,
    ).payload;
    expect(payload.rival_entry_id).toBe(c.rival_entry_id);
    expect(payload.top100?.weight).toBe(c.weight);
    expect(payload.expected_points_cost).toBeCloseTo(reference.expected_points_cost!, 9);
    expect(payload.moves.map((m) => m.reason_code)).toEqual(reference.moves!.map((m) => m.reason));
  });
});
