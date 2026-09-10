import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import type { Language } from "../../../i18n/messages";
import type { MemberChipRecommendations } from "../types";
import { ChipRecommendations } from "./ChipRecommendations";
import { isAdvicePayload } from "./adviceShape";

afterEach(cleanup);

const players = [
  "GK",
  "GK",
  "DEF",
  "DEF",
  "DEF",
  "DEF",
  "DEF",
  "MID",
  "MID",
  "MID",
  "MID",
  "MID",
  "FWD",
  "FWD",
  "FWD",
].map((position, index) => ({
  player_id: index + 1,
  name: `Player ${index + 1}`,
  short_name: `P${index + 1}`,
  team: "1",
  position: position as "GK" | "DEF" | "MID" | "FWD",
  expected_points: 3,
}));
const value: MemberChipRecommendations = {
  contract_version: "member_chip_recommendations_v1",
  planning_policy_id: "member_planning_policy_v3",
  gameweeks: [5, 6, 7],
  control_solver_status: "OPTIMAL",
  control_optimality_gap: 0,
  comparisons: [
    {
      chip: "bboost",
      available_from_gameweek: 1,
      last_usable_gameweek: 19,
      remaining: 1,
      action: "play",
      gameweek: 6,
      expected_points_gain: 12.5,
      reason: "window_gain",
      solver_status: "FEASIBLE",
      optimality_gap: 0.5,
      decision: {
        gameweek: 6,
        chip: "bboost",
        expected_own_points: 48,
        transfer_hit_points: 0,
        starting_xi: [0, 2, 3, 4, 7, 8, 9, 10, 12, 13, 14].map((index) => players[index]),
        bench: [1, 5, 6, 11].map((index) => players[index]),
        captain: players[7],
        vice_captain: players[8],
      },
    },
    {
      chip: "bboost",
      available_from_gameweek: 20,
      last_usable_gameweek: 38,
      remaining: 1,
      action: "hold",
      gameweek: null,
      expected_points_gain: null,
      reason: "outside_horizon",
      solver_status: null,
      optimality_gap: null,
      decision: null,
    },
  ],
};

describe.each<Language>(["tr", "en"])("chip publication in %s", (language) => {
  it("shows price, independent copies, expiry and missing future price without probability claims", () => {
    const { container } = render(
      <LanguageProvider initialLanguage={language}>
        <ChipRecommendations value={value} />
      </LanguageProvider>,
    );
    expect(
      screen.getByRole("heading", { name: language === "tr" ? "Chip takvimi" : "Chip calendar" }),
    ).toBeTruthy();
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(container.textContent).toContain(
      language === "tr" ? "beklenen +12,5 puan" : "expected +12.5 points",
    );
    expect(container.textContent).toContain("GW19");
    expect(container.textContent).toContain("GW38");
    expect(container.textContent).toContain(language === "tr" ? "Tut" : "Hold");
    expect(container.textContent).toContain(
      language === "tr" ? "henüz doğrulanmadı" : "not yet proved",
    );
    expect(container.textContent).not.toMatch(/probab|olasılık|yüzde|ihtimal|şans|%/i);
  });
});

it("validates the optional chip contract while retaining legacy advice", () => {
  const advice = { ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload, gameweek: 5 };
  expect(isAdvicePayload(advice)).toBe(true);
  expect(isAdvicePayload({ ...advice, chip_recommendations: value })).toBe(true);
  expect(
    isAdvicePayload({
      ...advice,
      chip_recommendations: {
        ...value,
        comparisons: [{ ...value.comparisons[0], expected_points_gain: Infinity }],
      },
    }),
  ).toBe(false);
  expect(
    isAdvicePayload({ ...advice, chip_recommendations: { ...value, contract_version: "unknown" } }),
  ).toBe(false);
});

it.each([
  "no_decision",
  "wrong_week",
  "expired",
  "hold_with_decision",
  "duplicate_window",
  "duplicate_player",
  "captain_on_bench",
  "wrong_chip",
  "positive_hold",
  "wrong_horizon",
])("refuses contradictory chip evidence: %s", (problem) => {
  const block = structuredClone(value);
  const row = block.comparisons[0];
  if (problem === "no_decision") row.decision = null;
  else if (problem === "wrong_week") row.decision!.gameweek = 7;
  else if (problem === "expired") row.last_usable_gameweek = 4;
  else if (problem === "hold_with_decision") row.action = "hold";
  else if (problem === "duplicate_window") block.comparisons.push(structuredClone(row));
  else if (problem === "duplicate_player") row.decision!.bench[0] = row.decision!.starting_xi[0];
  else if (problem === "captain_on_bench") row.decision!.captain = row.decision!.bench[0];
  else if (problem === "wrong_chip") row.decision!.chip = "3xc";
  else if (problem === "positive_hold")
    Object.assign(row, {
      action: "hold",
      gameweek: null,
      decision: null,
      reason: "no_positive_gain",
    });
  else if (problem === "wrong_horizon") block.gameweeks = [6, 7, 8];
  const advice = {
    ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload,
    gameweek: 5,
    chip_recommendations: block,
  };
  expect(isAdvicePayload(advice)).toBe(false);
});
