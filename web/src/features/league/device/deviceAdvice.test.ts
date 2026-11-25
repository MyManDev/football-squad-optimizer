import { describe, expect, it } from "vitest";

import fixture from "../../../fixtures/device-plan/instances.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { deviceAdviceEnvelope } from "./deviceAdvice";
import { checkedPreferences } from "../advice/decisionPreferences";
import type { DevicePlanAnswer, DevicePlanDocument, DeviceRivalFields } from "./types";

const world = fixture.rivals;
const document = world.document as unknown as DevicePlanDocument;
const squad = mockEntrySquadEnvelopes[35249001]!.payload;

/** What the server answered for the case, in the answer's own field names. */
type Reference = Pick<
  DevicePlanAnswer,
  | "starting_xi"
  | "captain"
  | "vice_captain"
  | "bench"
  | "transfers_in"
  | "transfers_out"
  | "transfer_hit_points"
  | "expected_own_points"
  | "moves"
  | "expected_gain_vs_hold"
> &
  Omit<DeviceRivalFields, "mode" | "rival_entry_id" | "alternative_plan">;
const reference = world.cases.find(
  (c) => c.entry_id === 101 && c.rival_entry_id === 202 && c.strategy === "fark-yarat",
)!.reference as unknown as Reference;

const plain: DevicePlanAnswer = {
  objective_scaled: 0,
  objective: 0,
  squad: [...reference.starting_xi, ...reference.bench],
  starting_xi: reference.starting_xi,
  captain: reference.captain,
  vice_captain: reference.vice_captain,
  bench: reference.bench,
  transfers_in: reference.transfers_in,
  transfers_out: reference.transfers_out,
  transfer_hit_points: reference.transfer_hit_points,
  expected_own_points: reference.expected_own_points,
  hold_points: 0,
  moves: reference.moves,
  expected_gain_vs_hold: reference.expected_gain_vs_hold,
  chip: null,
  seconds: 0.1,
};

const rival: DeviceRivalFields = {
  mode: "fark-yarat",
  rival_entry_id: 35249002,
  expected_points_cost: reference.expected_points_cost,
  expected_points_cost_ceiling: reference.expected_points_cost_ceiling,
  overlap_count: reference.overlap_count,
  transfer_cap: reference.transfer_cap,
  overlap_target: reference.overlap_target,
  overlap_applied: reference.overlap_applied,
  plan_kind: reference.plan_kind,
  alternative_plan: null,
  expected_gap_vs_rival: reference.expected_gap_vs_rival,
  captain_agreement: reference.captain_agreement,
};

it("uses the same coefficient precision in both views of a net-points transfer", () => {
  const id = plain.transfers_in[0]!;
  const changed = {
    ...document,
    players: document.players.map((p) =>
      p.id === id ? { ...p, expected_points: p.expected_points + 0.0004 } : p,
    ),
  };
  const plan = deviceAdviceEnvelope(
    changed,
    squad,
    { ...plain, preferences: checkedPreferences({ net_points_priority: true }) },
    new Date(),
    352490,
  ).payload;
  const top = plan.moves.find((move) => move.player_in?.player_id === id)!.player_in!;
  const weekly = plan.plan_weeks![0]!.transfers_in.find((p) => p.player_id === id)!;
  const source = changed.players.find((p) => p.id === id)!;
  expect(top.expected_points).toBe(source.coefficients[2] / changed.rules.expected_points_scale);
  expect(weekly.expected_points).toBe(top.expected_points);
});

describe("the moves of a plan solved on the device", () => {
  it("carry the reason the server gives the same plan's moves", () => {
    expect(plain.moves.length).toBeGreaterThan(0);
    const at = new Date("2026-10-03T01:02:03Z");
    // The pure-points plan's moves are a points gain.
    const pure = deviceAdviceEnvelope(document, squad, plain, at, 352490).payload;
    expect(pure.moves.map((move) => move.reason_code)).toEqual(
      plain.moves.map(() => "points_gain"),
    );
    // A rival strategy's are its trade-off, as build_advice_payload labels a mode's moves.
    const banded = deviceAdviceEnvelope(document, squad, { ...plain, rival }, at, 352490).payload;
    expect(banded.mode).toBe("fark-yarat");
    // The league is the tree's: the capture's table names none.
    expect(pure.league_id).toBe(352490);
    expect(banded.moves.map((move) => move.reason_code)).toEqual(
      plain.moves.map(() => "mode_tradeoff"),
    );
  });
});
