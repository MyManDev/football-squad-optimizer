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
