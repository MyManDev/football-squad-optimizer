import { describe, expect, it } from "vitest";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { AdviceResponseError, checkedAdvice } from "./adviceResponse";

const request = { leagueId: 352490, entryId: 101, strategy: "saf-puan", window: 3 } as const;

describe("nested published advice", () => {
  it("never serves the other model or an unidentified experimental result", () => {
    const old = mockEntryAdviceEnvelope(101, "saf-puan", 3);
    const football = {
      ...old,
      payload: {
        ...old.payload,
        prediction_model: {
          id: "football",
          version: "football_team_share_v1",
          experimental: true,
          fingerprint: "a".repeat(64),
        },
      },
    };
    expect(() => checkedAdvice(old, { ...request, model: "football" })).toThrow(
      AdviceResponseError,
    );
    expect(() => checkedAdvice(football, request)).toThrow(AdviceResponseError);
    expect(checkedAdvice(football, { ...request, model: "football" })).toBe(football);
    for (const patch of [{ fingerprint: "" }, { experimental: false }, { version: "other" }]) {
      expect(() =>
        checkedAdvice(
          {
            ...football,
            payload: {
              ...football.payload,
              prediction_model: { ...football.payload.prediction_model, ...patch },
            },
          },
          { ...request, model: "football" },
        ),
      ).toThrow(AdviceResponseError);
    }
  });
  it.each([
    { moves: [null] },
    { moves: [{ move_id: "1", player_out: null, player_in: { player_id: 1 } }] },
    { captain: { player_id: true } },
    { bench: [null] },
    { plan_weeks: [{ gameweek: 1 }] },
    { missing_fields: [null] },
    { expected_points_cost: Infinity },
    { data_quality: "invented" },
    { window: 1.5 },
    { squad_basis: null },
    { squad_basis: 2 },
    { alternative_plan: { kind: "with_hits" } },
  ])("refuses malformed nested fields %j", (patch) => {
    const envelope = mockEntryAdviceEnvelope(101, "saf-puan", 3);
    expect(() =>
      checkedAdvice({ ...envelope, payload: { ...envelope.payload, ...patch } }, request),
    ).toThrow(AdviceResponseError);
  });

  it("accepts a complete multi-week example without changing its bytes", () => {
    const envelope = mockEntryAdviceEnvelope(101, "saf-puan", 3);
    expect(checkedAdvice(envelope, request)).toBe(envelope);
  });
});

it("separates automatic hold/play, manual choice and Top100 identities", () => {
  const base = mockEntryAdviceEnvelope(101, "saf-puan", 3);
  const request = {
    leagueId: base.payload.league_id,
    entryId: 101,
    strategy: "saf-puan" as const,
    window: 3 as const,
    chip: "auto" as const,
    top100Weight: 20 as const,
  };
  for (const selected_chip of [null, "3xc"] as const) {
    const answer = {
      ...base,
      payload: {
        ...base.payload,
        chip: selected_chip,
        chip_strategy: {
          version: "model_opportunity_reservation_v1",
          mode: "auto",
          requested_chip: "auto",
          selected_chip,
          top100_weight: 20,
          objective_gap: 0,
          objective_basis: "selection_utility_with_chip_reserve",
          experimental: true,
          reservations: [],
          limits: [],
        },
      },
    };
    expect(checkedAdvice(answer, request)).toBe(answer);
    expect(() => checkedAdvice(answer, { ...request, chip: null })).toThrow(AdviceResponseError);
    expect(() => checkedAdvice(answer, { ...request, chip: "3xc" })).toThrow(AdviceResponseError);
    expect(() => checkedAdvice(answer, { ...request, top100Weight: 0 })).toThrow(
      AdviceResponseError,
    );
    expect(() =>
      checkedAdvice({ ...answer, payload: { ...answer.payload, chip: "bboost" } }, request),
    ).toThrow(AdviceResponseError);
  }
});
