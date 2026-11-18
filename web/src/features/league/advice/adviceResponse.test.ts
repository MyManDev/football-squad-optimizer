import { describe, expect, it } from "vitest";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import type { AdvicePlanWeek } from "../types";
import { AdviceResponseError, checkedAdvice } from "./adviceResponse";
import { checkedPreferences } from "./decisionPreferences";

const request = { leagueId: 352490, entryId: 101, strategy: "saf-puan", window: 3 } as const;

describe("nested published advice", () => {
  it.each(["opening", "later", "alternative"] as const)(
    "refuses negative %s transfer hits before they can inflate net points",
    (where) => {
      const envelope = mockEntryAdviceEnvelope(101, "saf-puan", 3);
      if (where === "opening") envelope.payload.transfer_hit_points = -4;
      if (where === "later")
        envelope.payload.plan_weeks = [0, 1, 2].map((offset) => ({
          gameweek: envelope.payload.gameweek + offset,
          transfers_in: [],
          transfers_out: [],
          chip: null,
          free_transfers_before: 1,
          free_transfers_after: 2,
          expected_points: 50,
          transfer_hit_points: offset === 1 ? -4 : 0,
        }));
      if (where === "alternative")
        envelope.payload.alternative_plan = {
          kind: "with_hits",
          overlap_applied: 0,
          transfer_hit_points: -4,
          expected_points_cost: 0,
        };
      expect(() => checkedAdvice(envelope, request)).toThrow(AdviceResponseError);
    },
  );

  it("keeps legitimate signed point differences while accepting zero hit charges", () => {
    const envelope = mockEntryAdviceEnvelope(35249001, "saf-puan", 3);
    envelope.payload.transfer_hit_points = 0;
    envelope.payload.expected_gain_vs_hold = -3;
    expect(envelope.payload.moves.length).toBeGreaterThan(0);
    for (const move of envelope.payload.moves) move.expected_points_delta = -3;
    expect(checkedAdvice(envelope, { ...request, entryId: 35249001 })).toBe(envelope);
  });

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
    const contextual = {
      ...football,
      payload: {
        ...football.payload,
        prediction_model: {
          ...football.payload.prediction_model,
          version: "football_contextual_v3",
        },
      },
    };
    expect(checkedAdvice(contextual, { ...request, model: "football" })).toBe(contextual);
    for (const version of [
      "football_match_context_v1",
      "football_joint_role_minutes_v1",
      "football_joint_role_retained_history_v1",
      "football_joint_role_retained_flags_v2",
      "football_composite_v1",
      "football_team_form_v1",
    ]) {
      const joint = {
        ...football,
        payload: {
          ...football.payload,
          prediction_model: { ...football.payload.prediction_model, version },
        },
      };
      expect(checkedAdvice(joint, { ...request, model: "football" })).toBe(joint);
      expect(() => checkedAdvice(joint, request)).toThrow(AdviceResponseError);
    }
    for (const patch of [
      { fingerprint: "" },
      { experimental: false },
      { version: "other" },
      { version: "football_joint_role_retained_flags_v1" },
    ]) {
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

  it("requires the selected-week preference echo and an actual Wildcard in the scheduled week", () => {
    const envelope = mockEntryAdviceEnvelope(101, "saf-puan", 3);
    const preferences = checkedPreferences({
      week_rules: [{ week: 1, rules: { hold_transfers: true } }],
      wildcard_week: 2,
    });
    const selected = { ...request, preferences, chip: null };
    const weeks = [0, 1, 2].map((offset) => ({
      gameweek: envelope.payload.gameweek + offset,
      transfers_in: [],
      transfers_out: [],
      chip: null,
      expected_points: 45,
      transfer_hit_points: 0,
      free_transfers_before: 1,
      free_transfers_after: 2,
    }));
    const answer = {
      ...envelope,
      payload: {
        ...envelope.payload,
        preferences,
        preferences_scope: "selected_weeks",
        chip: null,
        chip_strategy: {
          version: "model_opportunity_reservation_v2",
          mode: "manual",
          requested_chip: "wildcard",
          selected_chip: null,
          top100_weight: 0,
          objective_gap: 0,
          objective_basis: "selection_utility_with_chip_reserve",
          experimental: true,
          reservations: [],
          limits: [],
        },
        plan_weeks: weeks.map((week, index) => ({
          ...week,
          chip: index === 1 ? "wildcard" : null,
        })),
      },
    };
    expect(checkedAdvice(answer, selected)).toBe(answer);
    expect(() =>
      checkedAdvice(
        { ...answer, payload: { ...answer.payload, preferences_scope: "all_selected_weeks" } },
        selected,
      ),
    ).toThrow(/preferences/);
    expect(() =>
      checkedAdvice({ ...answer, payload: { ...answer.payload, plan_weeks: weeks } }, selected),
    ).toThrow(/Wildcard/);
  });

  it("requires the declared opening preferences to change the returned opening state", () => {
    const envelope = mockEntryAdviceEnvelope(35249001, "saf-puan", 3);
    const preferences = checkedPreferences({
      hold_opening_transfers: true,
      min_opening_bank_tenths: 25,
    });
    const selected = { ...request, entryId: envelope.payload.entry_id, preferences };
    const weeks: AdvicePlanWeek[] = [0, 1, 2].map((offset) => ({
      gameweek: envelope.payload.gameweek + offset,
      transfers_in: [],
      transfers_out: [],
      chip: null,
      expected_points: 45,
      transfer_hit_points: 0,
      free_transfers_before: 1,
      free_transfers_after: 2,
    }));
    const answer = {
      ...envelope,
      payload: {
        ...envelope.payload,
        moves: [],
        chip: null,
        preferences,
        preferences_scope: "selected_weeks",
        bank_after_tenths: 25,
        plan_weeks: weeks,
      },
    };
    const changed = (patch: Partial<typeof answer.payload>) => ({
      ...answer,
      payload: { ...answer.payload, ...patch },
    });
    expect(checkedAdvice(answer, selected)).toBe(answer);
    expect(() =>
      checkedAdvice(changed({ preferences_scope: "all_selected_weeks" }), selected),
    ).toThrow(/preferences/);
    expect(() => checkedAdvice(changed({ bank_after_tenths: 24 }), selected)).toThrow(/budget/);
    const missingBank = JSON.parse(JSON.stringify(changed({ bank_after_tenths: undefined })));
    expect(() => checkedAdvice(missingBank, selected)).toThrow(/budget/);
    expect(() =>
      checkedAdvice(
        changed({
          plan_weeks: [
            { ...weeks[0]!, transfers_in: [envelope.payload.starting_xi![0]!] },
            ...weeks.slice(1),
          ],
        }),
        selected,
      ),
    ).toThrow(/hold transfers/);
  });
});

it.each(["model_opportunity_reservation_v1", "model_opportunity_reservation_v2"])(
  "separates automatic hold/play, manual choice and Top100 identities for %s",
  (version) => {
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
            version,
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
      expect(() =>
        checkedAdvice(
          {
            ...answer,
            payload: {
              ...answer.payload,
              chip_strategy: { ...answer.payload.chip_strategy, version: "unknown" },
            },
          },
          request,
        ),
      ).toThrow(AdviceResponseError);
      expect(() => checkedAdvice(answer, { ...request, chip: null })).toThrow(AdviceResponseError);
      expect(() => checkedAdvice(answer, { ...request, chip: "3xc" })).toThrow(AdviceResponseError);
      expect(() => checkedAdvice(answer, { ...request, top100Weight: 0 })).toThrow(
        AdviceResponseError,
      );
      expect(() =>
        checkedAdvice({ ...answer, payload: { ...answer.payload, chip: "bboost" } }, request),
      ).toThrow(AdviceResponseError);
    }
  },
);
