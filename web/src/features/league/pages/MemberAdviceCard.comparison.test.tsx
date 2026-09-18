import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, expect, it } from "vitest";
import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import { AdviceCard } from "./MemberAdviceCard";

afterEach(cleanup);
const ENTRY = 35249001;
function plan(mode: "saf-puan" | "fark-yarat", score: number): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3);
  return {
    ...base,
    payload: {
      ...base.payload,
      mode,
      expected_points_cost: 0,
      expected_points_cost_ceiling: 0,
      plan_weeks: base.payload.plan_weeks!.map((week) => ({
        ...week,
        expected_points: score,
        transfer_hit_points: 4,
      })),
    },
  };
}
function show(
  selected: LeagueViewEnvelope<EntryAdvice>,
  control: LeagueViewEnvelope<EntryAdvice> | null,
  language: "en" | "tr" = "en",
) {
  render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter>
        <AdviceCard
          shown={{ envelope: selected, origin: "computed" }}
          squad={mockEntrySquadEnvelopes[ENTRY]}
          rivalSquad={null}
          windowControl={control}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
}
it.each(["en", "tr"] as const)(
  "shows two base totals and limits without a difference in %s",
  (language) => {
    const selected = plan("fark-yarat", 70);
    show(selected, plan("saf-puan", 60), language);
    const copy = MESSAGES[language].leagueMembers;
    const region = screen.getByRole("region", { name: copy.windowComparisonTitle });
    expect(within(region).getByText(language === "en" ? "198.0" : "198,0")).toBeInTheDocument();
    expect(within(region).getByText(language === "en" ? "168.0" : "168,0")).toBeInTheDocument();
    expect(region).toHaveTextContent(copy.windowLimits);
    expect(region).toHaveTextContent(copy.windowComparisonBasis);
    expect(region).not.toHaveTextContent("30");
  },
);
it.each([
  { source_snapshot_id: "different" },
  { source_snapshot_id: undefined },
  { entry_id: ENTRY + 1 },
  { window: 5 },
  { gameweek: 3 },
  { mode: "ortak-koru" },
  { plan_weeks: [] },
  { top100: { weight: 20 } },
  { evidence: {} },
  { chip: "bboost" },
])("hides a control that cannot describe the same window: %j", (change) => {
  const control = plan("saf-puan", 60);
  Object.assign(control.payload, change);
  show(plan("fark-yarat", 70), control);
  expect(
    screen.queryByRole("region", { name: MESSAGES.en.leagueMembers.windowComparisonTitle }),
  ).toBeNull();
});
it("does not use first-week points when a later week has no total", () => {
  const control = plan("saf-puan", 60);
  control.payload.plan_weeks![1]!.expected_points = Number.NaN;
  show(plan("fark-yarat", 70), control);
  expect(
    screen.queryByRole("region", { name: MESSAGES.en.leagueMembers.windowComparisonTitle }),
  ).toBeNull();
});
it("leaves a missing published control absent for a computed plan", () => {
  show(plan("fark-yarat", 70), null);
  expect(
    screen.queryByRole("region", { name: MESSAGES.en.leagueMembers.windowComparisonTitle }),
  ).toBeNull();
});

it("shows a Top 100 pure-points selection against the published plan at zero", () => {
  const selected = plan("saf-puan", 55);
  selected.payload.top100 = { weight: 20, changed: true, price_basis: "base_projection" };
  show(selected, plan("saf-puan", 60));
  const region = screen.getByRole("region", {
    name: MESSAGES.en.leagueMembers.windowComparisonTitle,
  });
  expect(region).toHaveTextContent("153.0");
  expect(region).toHaveTextContent("168.0");
});
