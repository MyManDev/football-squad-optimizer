import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import type { AdviceLineupExpectation } from "../types";
import { ExpectedLineup } from "./ExpectedLineup";
import { isAdvicePayload } from "./adviceShape";

afterEach(cleanup);
const expectation: AdviceLineupExpectation = {
  version: "expected_lineup_v1",
  expected_net_points: 42.75,
  starting_points: 38,
  autosub_points: 2.5,
  captain_bonus_points: 6,
  vice_bonus_points: 0.25,
  bench_boost_points: 0,
  assumptions: [
    "independent_player_week_appearances",
    "any_positive_gameweek_minutes_including_cameos_block_autosubs",
  ],
};

it.each(["tr", "en"] as const)(
  "explains automatic substitutes and vice recovery in %s",
  (language) => {
    const view = {
      ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload,
      transfer_hit_points: 4,
      lineup_expectation: expectation,
    };
    render(
      <LanguageProvider initialLanguage={language}>
        <ExpectedLineup view={view} />
      </LanguageProvider>,
    );
    const region = screen.getByTestId("lineup-expectation");
    expect(region).toHaveTextContent(
      language === "tr"
        ? "Yedeklere sabit bir puan payı eklenmez"
        : "No fixed share of bench points is added",
    );
    expect(region).toHaveTextContent(
      language === "tr" ? "yardımcısının ek puanı" : "Vice-captain bonus",
    );
    expect(region).not.toHaveTextContent(
      language === "tr" ? "birbirinden bağımsız" : "treated as independent",
    );
    expect(region).not.toHaveTextContent(
      language === "tr" ? "Oynama varsayımları" : "Playing assumptions",
    );
    expect(region).not.toHaveTextContent("independent_player_week_appearances");
  },
);

it("keeps legacy documents unchanged and rejects invalid expected scores", () => {
  const view = mockEntryAdviceEnvelope(101, "saf-puan", 3).payload;
  render(
    <LanguageProvider initialLanguage="en">
      <ExpectedLineup view={view} />
    </LanguageProvider>,
  );
  expect(screen.queryByTestId("lineup-expectation")).not.toBeInTheDocument();
  expect(isAdvicePayload({ ...view, lineup_expectation: expectation })).toBe(true);
  expect(
    isAdvicePayload({ ...view, lineup_expectation: { ...expectation, vice_bonus_points: NaN } }),
  ).toBe(false);
  expect(
    isAdvicePayload({ ...view, lineup_expectation: { ...expectation, scoring_multipliers: {} } }),
  ).toBe(false);
});
