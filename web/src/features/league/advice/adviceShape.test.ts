/// <reference types="node" />
// @vitest-environment node
import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { isAdvicePayload } from "./adviceShape";

/** The committed contract the Python publisher generates and this shape mirrors by hand. */
const schema = JSON.parse(
  readFileSync(
    new URL("../../../../../docs/contracts/advice_read_v1.schema.json", import.meta.url),
    "utf-8",
  ),
) as { properties: { payload: { properties: Record<string, unknown>; required: string[] } } };

/**
 * Ask the shape which payload keys it checks, without exporting its tables: a valid
 * payload behind a Proxy that notes every key read (a required key) and every key
 * probed with `in` first (an optional key). The shape must accept the payload, or its
 * short-circuit would stop the walk before the last key.
 */
function checkedKeys(): { required: Set<string>; optional: Set<string> } {
  const required = new Set<string>();
  const optional = new Set<string>();
  const payload: object = mockEntryAdviceEnvelope(101, "saf-puan", 3).payload;
  const probe = new Proxy(payload, {
    has(target, key) {
      if (typeof key === "string") optional.add(key);
      return Reflect.has(target, key);
    },
    get(target, key) {
      if (typeof key === "string" && !optional.has(key)) required.add(key);
      return Reflect.get(target, key);
    },
  });
  expect(isAdvicePayload(probe)).toBe(true);
  return { required, optional };
}

it("requires exactly the payload keys the served schema requires", () => {
  const { required } = checkedKeys();
  expect([...required].sort()).toEqual([...schema.properties.payload.required].sort());
});

it("checks exactly the payload keys the served schema declares", () => {
  const { required, optional } = checkedKeys();
  expect([...required, ...optional].sort()).toEqual(
    Object.keys(schema.properties.payload.properties).sort(),
  );
});

it("validates the whole multiweek comparison and rejects inconsistent or extra fields", () => {
  const payload = mockEntryAdviceEnvelope(101, "saf-puan", 3).payload;
  payload.plan_weeks = Array.from({ length: 3 }, (_, i) => ({
    gameweek: payload.gameweek + i,
    transfers_in: [],
    transfers_out: [],
    transfer_hit_points: 0,
    chip: null,
    free_transfers_before: 1,
    free_transfers_after: 2,
    expected_points: 40 + i,
  }));
  const weeks = payload.plan_weeks!;
  const nets = weeks.map((w) => w.expected_points - w.transfer_hit_points);
  const total = nets.reduce((sum, value) => sum + value, 0);
  payload.mode = "ortak-koru";
  payload.rival_entry_id = 202;
  payload.window_comparison = {
    policy_id: "first_week_rival_horizon_v1",
    rival_entry_id: 202,
    rival_gameweek: payload.gameweek - 1,
    overlap_scope: "first_week_squad_vs_captured_rival_xi",
    overlap_minimum: 9,
    overlap_maximum: null,
    overlap_actual: 9,
    first_week_net_points: nets[0]!,
    control_first_week_net_points: nets[0]!,
    total_net_points: total,
    control_total_net_points: total,
    net_points_difference: 0,
    solver_status: "OPTIMAL",
    control_solver_status: "OPTIMAL",
    optimality_gap: 0,
    control_optimality_gap: 0,
  };
  payload.solver_status = "OPTIMAL";
  payload.optimality_gap = 0;
  expect(isAdvicePayload(payload)).toBe(true);
  for (const change of [
    { total_net_points: total + 1 },
    { rival_entry_id: 101 },
    { overlap_actual: 8 },
    { toString: "extra" },
  ]) {
    expect(
      isAdvicePayload({
        ...payload,
        window_comparison: { ...payload.window_comparison, ...change },
      }),
    ).toBe(false);
  }
  expect(isAdvicePayload({ ...payload, window: 1 })).toBe(false);
  expect(isAdvicePayload({ ...payload, window_comparison: undefined })).toBe(false);
});
