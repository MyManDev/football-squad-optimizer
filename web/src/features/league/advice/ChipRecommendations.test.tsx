import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import type { Language } from "../../../i18n/messages";
import type { MemberChipRecommendations } from "../types";
import { ChipRecommendations } from "./ChipRecommendations";
import { isAdvicePayload } from "./adviceShape";

afterEach(cleanup);

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
      decision: null,
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
  const advice = mockEntryAdviceEnvelope(101, "saf-puan", 3).payload;
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
