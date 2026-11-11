import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import type { AdviceRolePointComponents, EntryAdvice } from "../types";
import { RoleForecast } from "./RoleForecast";
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
          expected_minutes: 34,
          captured_eligibility_multiplier: 0.5,
          news_applied: true,
        },
      ],
    },
  };
}

it.each(["tr", "en"] as const)(
  "shows expected minutes alone, without modeled probabilities or how they were read, in %s",
  (language) => {
    const view = example();
    expect(isAdvicePayload(view)).toBe(true);
    render(
      <LanguageProvider initialLanguage={language}>
        <RoleForecast view={view} />
      </LanguageProvider>,
    );
    const section = screen.getByTestId("role-forecast");
    expect(section).toHaveTextContent(
      language === "tr" ? "Beklenen dakika: 34,0" : "Expected Minutes: 34.0",
    );
    expect(section.textContent).not.toMatch(AS_A_CHANCE);
    expect(section).not.toHaveTextContent(
      language === "tr" ? "geçmiş maçlardaki ilk 11" : "past records of starts",
    );
    expect(section).not.toHaveTextContent(
      language === "tr" ? "kesinleşmiş bir ilk 11 değildir" : "not a confirmed lineup",
    );
    expect(section).not.toHaveTextContent(
      language === "tr" ? "Bağımsız doğruluk ölçümü" : "Independent accuracy validation",
    );
    expect(section).not.toHaveTextContent(
      language === "tr" ? "Kaynaklı oynama veya süre" : "A sourced availability or minutes",
    );
    expect(section).not.toHaveTextContent("9999");
    expect(screen.queryByTestId("role-point-components")).not.toBeInTheDocument();
  },
);

it("says nothing more for an unknown starting role, and refuses out-of-range or extra fields", () => {
  const view = example();
  const row = view.role_forecast!.rows[0]!;
  row.status = "unavailable_no_known_start_labels";
  expect(isAdvicePayload(view)).toBe(true);
  render(
    <LanguageProvider initialLanguage="en">
      <RoleForecast view={view} />
    </LanguageProvider>,
  );
  expect(screen.getByTestId("role-forecast")).toHaveTextContent("Expected Minutes: 34.0");
  expect(screen.getByTestId("role-forecast").textContent).not.toMatch(AS_A_CHANCE);
  expect(screen.getByTestId("role-forecast")).not.toHaveTextContent(
    "Insufficient recorded starting-role evidence",
  );
  row.captured_eligibility_multiplier = 1.1;
  expect(isAdvicePayload(view)).toBe(false);
  row.captured_eligibility_multiplier = 0.5;
  expect(
    isAdvicePayload({ ...view, role_forecast: { ...view.role_forecast, win_probability: 0.8 } }),
  ).toBe(false);
  expect(
    isAdvicePayload({ ...view, role_forecast: { ...view.role_forecast, calibration: "verified" } }),
  ).toBe(false);
});

it.each([
  "start_probability",
  "cameo_probability",
  "zero_probability",
  "unknown_role_probability",
  "sixty_minute_probability",
])("rejects the internal model field %s at the member payload boundary", (field) => {
  const view = example();
  const row = view.role_forecast!.rows[0]!;
  expect(
    isAdvicePayload({
      ...view,
      role_forecast: { ...view.role_forecast, rows: [{ ...row, [field]: 0.5 }] },
    }),
  ).toBe(false);
});

const pointComponents: AdviceRolePointComponents = {
  appearance: 0.7,
  goals: 0.8,
  assists: 0.4,
  clean_sheet: 0.3,
  defcon: 0.2,
  other: -0.1,
  clipping: 0,
  total: 2.3,
};

it.each(["tr", "en"] as const)(
  "expands supplied individual fixture points with an honest signed residual in %s",
  (language) => {
    const view = example();
    view.role_forecast!.rows[0]!.point_components = pointComponents;
    expect(isAdvicePayload(view)).toBe(true);
    render(
      <LanguageProvider initialLanguage={language}>
        <RoleForecast view={view} />
      </LanguageProvider>,
    );
    const role = screen.getByTestId("role-forecast");
    fireEvent.click(role.querySelector(":scope > summary")!);
    const detail = screen.getByTestId("role-point-components");
    expect(detail).not.toHaveAttribute("open");
    fireEvent.click(detail.querySelector("summary")!);
    expect(detail).toHaveAttribute("open");
    expect(detail).toHaveTextContent(
      language === "tr" ? "Süre puanı: 0,70" : "Appearance Points: 0.70",
    );
    expect(detail).toHaveTextContent(
      language === "tr" ? "Diğer katkılar: -0,10" : "Other Contributions: -0.10",
    );
    expect(detail).toHaveTextContent(
      language === "tr" ? "Savunma katkısı: 0,20" : "Defensive Contributions: 0.20",
    );
    // The owner's word of 2026-11-11: the clean sheet is "gol yenmeyen maç" in Turkish.
    expect(detail).toHaveTextContent(
      language === "tr" ? "Gol yenmeyen maç: 0,30" : "Clean Sheet: 0.30",
    );
    expect(detail.textContent!.toLocaleLowerCase("tr")).not.toContain("kuru kale");
    expect(detail).toHaveTextContent(
      language === "tr" ? "Toplam oyuncu puanı: 2,30" : "Total Player Points: 2.30",
    );
    expect(detail).not.toHaveTextContent(
      language === "tr" ? "yalnızca bu maç" : "this fixture only",
    );
    expect(detail).not.toHaveTextContent(
      language === "tr"
        ? "Kaptan çarpanı ve Top100 ağırlığı öncesidir"
        : "Before the captain multiplier and the Top100 weight",
    );
    expect(detail).not.toHaveTextContent(
      language === "tr" ? "zaten bir kez uygulanmıştır" : "already applied once",
    );
  },
);

it("counts the floor at zero under the other term, so the rows add up to the total", () => {
  const view = example();
  view.role_forecast!.rows[0]!.point_components = {
    appearance: 0.1,
    goals: 0,
    assists: 0,
    clean_sheet: 0,
    defcon: 0,
    other: -0.4,
    clipping: 0.3,
    total: 0,
  };
  expect(isAdvicePayload(view)).toBe(true);
  render(
    <LanguageProvider initialLanguage="en">
      <RoleForecast view={view} />
    </LanguageProvider>,
  );
  const detail = screen.getByTestId("role-point-components");
  expect(detail).toHaveTextContent("Other Contributions: -0.10");
  expect(detail).not.toHaveTextContent("Zero-floor adjustment");
  expect(detail).toHaveTextContent("Total Player Points: 0.00");
  const rows = [...detail.querySelectorAll(":scope > ul .num")].map((cell) =>
    Number(cell.textContent),
  );
  expect(rows).toHaveLength(6);
  expect(rows.reduce((sum, row) => sum + row, 0)).toBeCloseTo(0, 2);
});

it.each([
  ...["appearance", "goals", "assists", "clean_sheet", "defcon", "clipping", "total"].map(
    (key) => ({ ...pointComponents, [key]: -0.1 }),
  ),
  ...Object.keys(pointComponents).map((key) => ({ ...pointComponents, [key]: Infinity })),
  { ...pointComponents, other: NaN },
  { ...pointComponents, total: "2.3" },
  { ...pointComponents, total: undefined },
  { ...pointComponents, invented_bonus: 1 },
  { total: 2.3 },
  null,
])("refuses incomplete, extra, nonfinite or invalid-sign point terms: %j", (invalid) => {
  const view = example();
  const row = view.role_forecast!.rows[0]!;
  expect(
    isAdvicePayload({
      ...view,
      role_forecast: { ...view.role_forecast, rows: [{ ...row, point_components: invalid }] },
    }),
  ).toBe(false);
});

it.each([
  "football_joint_role_minutes_v1",
  "football_joint_role_retained_history_v1",
  "football_joint_role_retained_flags_v2",
  "football_composite_v1",
] as const)("reads the same restricted role explanation for %s", (version) => {
  const view = example();
  view.role_forecast!.model_version = version;
  expect(isAdvicePayload(view)).toBe(true);
  render(
    <LanguageProvider initialLanguage="en">
      <RoleForecast view={view} />
    </LanguageProvider>,
  );
  expect(screen.getByTestId("role-forecast")).toHaveTextContent("Expected Minutes: 34.0");
  expect(screen.getByTestId("role-forecast").textContent).not.toMatch(AS_A_CHANCE);
  for (const invalid of ["unknown", "football_joint_role_retained_flags_v1"]) {
    expect(
      isAdvicePayload({
        ...view,
        role_forecast: { ...view.role_forecast, model_version: invalid },
      }),
    ).toBe(false);
  }
  expect(
    isAdvicePayload({
      ...view,
      role_forecast: {
        ...view.role_forecast,
        rows: [{ ...view.role_forecast!.rows[0], start_probability: 0.8 }],
      },
    }),
  ).toBe(false);
});
