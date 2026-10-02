import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import type { EntryAdvice } from "../types";
import { ParticipationEvidence } from "./ParticipationEvidence";
import { isAdvicePayload } from "./adviceShape";

afterEach(cleanup);
function example(): EntryAdvice {
  return {
    ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload,
    role_forecast: {
      version: "football_role_forecast_v1",
      model_version: "football_joint_role_minutes_v1",
      calibration: "not_independently_verified",
      scope: "current_gameweek_fixtures",
      rows: [
        {
          player_id: 123,
          name: "Test player",
          fixture_id: 9999,
          gameweek: 6,
          kickoff: "2026-10-11T12:30:00Z",
          status: "fitted_known_start_labels",
          start_probability: 0.4,
          cameo_probability: 0.1,
          zero_probability: 0.5,
          unknown_role_probability: 0,
          expected_minutes: 34,
          sixty_minute_probability: 0.3,
          captured_eligibility_multiplier: 0.5,
          news_applied: true,
        },
      ],
    },
  };
}

it.each(["tr", "en"] as const)(
  "shows model roles with limits even without a coach claim in %s",
  (language) => {
    const view = example();
    expect(isAdvicePayload(view)).toBe(true);
    render(
      <LanguageProvider initialLanguage={language}>
        <ParticipationEvidence view={view} />
      </LanguageProvider>,
    );
    const section = screen.getByTestId("role-forecast");
    expect(section).toHaveTextContent("40%");
    expect(section).toHaveTextContent("10%");
    expect(section).toHaveTextContent("50%");
    expect(section).toHaveTextContent(
      language === "tr" ? "Bağımsız doğruluk ölçümü" : "Independent accuracy validation",
    );
    expect(section).toHaveTextContent(
      language === "tr" ? "Kaynaklı oynama veya süre" : "A sourced availability or minutes",
    );
    expect(section).not.toHaveTextContent("9999");
  },
);

it("keeps unknown starting roles distinct from zero and refuses out-of-range or extra fields", () => {
  const view = example();
  const row = view.role_forecast!.rows[0]!;
  row.start_probability = null;
  row.cameo_probability = null;
  row.unknown_role_probability = 0.5;
  row.status = "unavailable_no_known_start_labels";
  expect(isAdvicePayload(view)).toBe(true);
  render(
    <LanguageProvider initialLanguage="en">
      <ParticipationEvidence view={view} />
    </LanguageProvider>,
  );
  expect(screen.getByTestId("role-forecast")).toHaveTextContent("Starts: —");
  expect(screen.getByTestId("role-forecast")).toHaveTextContent(
    "Insufficient recorded starting-role evidence",
  );
  row.zero_probability = 1.1;
  expect(isAdvicePayload(view)).toBe(false);
  row.zero_probability = 0.5;
  expect(
    isAdvicePayload({ ...view, role_forecast: { ...view.role_forecast, win_probability: 0.8 } }),
  ).toBe(false);
  expect(
    isAdvicePayload({ ...view, role_forecast: { ...view.role_forecast, calibration: "verified" } }),
  ).toBe(false);
});
