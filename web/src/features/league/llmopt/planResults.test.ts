import { describe, expect, it } from "vitest";

import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import type { ComputePhase } from "../advice/useAdviceJob";
import type { EntryAdvice } from "../types";
import { preferencePrice } from "./planResults";
import type { PriceTarget } from "./planRun";

const envelope = mockEntryAdviceEnvelope(35249001, "saf-puan", 1);
const request = {
  leagueId: 1,
  entryId: 35249001,
  strategy: "saf-puan",
  window: 1,
  season: envelope.payload.season,
  gameweek: envelope.payload.gameweek,
} as const;

function done(net: number, fields: Partial<EntryAdvice> = {}): ComputePhase {
  return {
    phase: "done",
    request,
    source: "api-cache",
    envelope: {
      ...envelope,
      payload: {
        ...envelope.payload,
        plan_weeks: undefined,
        lineup_expectation: undefined,
        moves: [],
        expected_own_points: net,
        transfer_hit_points: 0,
        ...fields,
      },
    },
  } as ComputePhase;
}

const rule = { kind: "include_player", player_id: 901, max_cost_tenths: 15 } as const;
const target = (outcome: PriceTarget["outcome"]): PriceTarget => ({ rule, outcome });
// A plan that signs a player, where the reference holds.
const moved = { moves: mockEntryAdviceEnvelope(35249001, "saf-puan", 3).payload.moves };

describe("preferencePrice", () => {
  it("prices a rule as the points its plan loses against the reference", () => {
    const price = preferencePrice(target(0), "Saka", done(50), [done(48.6, moved)], true);
    expect(price).toMatchObject({ status: "priced", aboveCeiling: false, ceiling: 15 });
    expect(price.status === "priced" && price.cost).toBeCloseTo(1.4);
  });

  it("marks a price above the rule's own limit", () => {
    const price = preferencePrice(target(0), "Saka", done(50), [done(48.4, moved)], true);
    expect(price).toMatchObject({ status: "priced", aboveCeiling: true });
  });

  it("costs nothing for a rule the required rules already meet", () => {
    expect(preferencePrice(target("same"), "Saka", done(50), [], true)).toMatchObject({
      status: "priced",
      cost: 0,
      aboveCeiling: false,
    });
  });

  it("waits while either plan is computing, or while its job can still start", () => {
    const working: ComputePhase = { phase: "requesting", request };
    expect(preferencePrice(target(0), "Saka", working, [], true).status).toBe("pending");
    expect(preferencePrice(target(0), "Saka", done(50), [working], true).status).toBe("pending");
    expect(preferencePrice(target(0), "Saka", done(50), [{ phase: "idle" }], true).status).toBe(
      "pending",
    );
    expect(preferencePrice(target(0), "Saka", done(50), [{ phase: "idle" }], false).status).toBe(
      "unavailable",
    );
  });

  it("passes a rule's own outcome through when it has no plan", () => {
    for (const outcome of ["conflict", "unavailable", "skipped"] as const)
      expect(preferencePrice(target(outcome), "Saka", done(50), [], true).status).toBe(outcome);
  });
});
