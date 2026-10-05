import { mockInformationReview } from "../../../fixtures/information";
import { isAdvicePayload } from "./adviceShape";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { InformationReview } from "./InformationReview";
import type { EntryAdvice } from "../types";

afterEach(cleanup);
it.each(["tr", "en"] as const)(
  "explains scenario bounds without inventing arrival odds in %s",
  (language) => {
    const data = view();
    data.information_review!.comparison = {
      version: "completed_policy_comparison_v1",
      basis: "expected_own_points",
      baseline_index: 0,
      scenario_ids: ["eligible", "unavailable"],
      news_arrival_probability: null,
      scope: "supplied_conditional_scenarios_only",
      terminal_resource_value_added: false,
      candidates: [
        {
          index: 0,
          action_kind: "hold",
          first_state: { bank_tenths: 25, free_transfers: 2 },
          scenario_min: 110,
          scenario_max: 130,
          branch_gaps_vs_baseline: { eligible: 0, unavailable: 0 },
          minimum_gap_vs_baseline: 0,
          maximum_gap_vs_baseline: 0,
          dominates_baseline: false,
          dominated_by: [],
        },
      ],
    };
    expect(isAdvicePayload(data)).toBe(true);
    render(
      <LanguageProvider initialLanguage={language}>
        <InformationReview view={data} />
      </LanguageProvider>,
    );
    const comparison = screen.getByTestId("policy-comparison");
    expect(comparison).toHaveTextContent("110");
    expect(comparison).toHaveTextContent("130");
    expect(comparison).not.toHaveTextContent(
      language === "tr" ? "güven aralığı değildir" : "not a confidence interval",
    );
    expect(comparison).not.toHaveTextContent(
      language === "tr" ? "olasılık atanmadı" : "No news-arrival probability",
    );
    expect(
      isAdvicePayload({
        ...data,
        information_review: {
          ...data.information_review,
          comparison: { ...data.information_review!.comparison, news_arrival_probability: 0.5 },
        },
      }),
    ).toBe(false);
  },
);
function view(): EntryAdvice {
  const base = mockEntryAdviceEnvelope(35249001, "saf-puan", 3).payload;
  return { ...base, information_review: mockInformationReview() };
}

it("shows conditional news, base points and hold without presenting future moves as certain", () => {
  render(
    <LanguageProvider initialLanguage="tr">
      <InformationReview view={view()} />
    </LanguageProvider>,
  );
  const region = screen.getByRole("region", { name: "Haber gelince plan nasıl değişir?" });
  expect(region).toHaveTextContent("FPL oynama değeri: 75/100");
  expect(region).not.toHaveTextContent("%");
  expect(region).toHaveTextContent("Bu hafta transfer yapma");
  expect(region).not.toHaveTextContent("kesin gelecek transfer tahmini değildir");
  expect(region).not.toHaveTextContent("Top100 ağırlığı puan kazancı değildir");
  expect(region).toHaveTextContent("Puanlar temel futbol tahmininden gelir");
  expect(within(region).getByText("Oynayamaz bilgisi gelirse")).toBeInTheDocument();
  expect(region).toHaveTextContent("2 ücretsiz transfer");
});
it("explains missing team components without showing an invented estimate", () => {
  const data = view();
  data.information_review!.status = "baseline_retained";
  data.information_review!.reason = "conditional_team_components_unavailable";
  data.information_review!.candidates = [];
  render(
    <LanguageProvider initialLanguage="tr">
      <InformationReview view={data} />
    </LanguageProvider>,
  );
  expect(screen.getByTestId("information-review")).toHaveTextContent(
    "Toplam puanlardan sakatlık senaryosu çıkarılmadı",
  );
  expect(screen.queryByText("Seçilen ilk hamle")).not.toBeInTheDocument();
});
it("does not relabel a missing weighted rescore as zero points", () => {
  const data = view();
  data.information_review!.candidates[0]!.expected_net_points = null;
  render(
    <LanguageProvider initialLanguage="en">
      <InformationReview view={data} />
    </LanguageProvider>,
  );
  expect(screen.getByTestId("information-review")).toHaveTextContent(
    "Expected window net points: —",
  );
});

it("rejects malformed conditional branches before rendering", () => {
  const data = view();
  expect(isAdvicePayload(data)).toBe(true);
  const malformed = {
    ...data,
    information_review: { ...data.information_review, candidates: [{}] },
  };
  expect(isAdvicePayload(malformed)).toBe(false);
  data.information_review!.source_playing_chance_percent = 150;
  expect(isAdvicePayload(data)).toBe(false);
});

it("distinguishes no alternative found from a completed comparison", () => {
  const data = view();
  data.information_review!.status = "baseline_retained";
  data.information_review!.reason = "no_distinct_alternative";
  data.information_review!.candidates = [];
  render(
    <LanguageProvider initialLanguage="en">
      <InformationReview view={data} />
    </LanguageProvider>,
  );
  expect(screen.getByTestId("information-review")).toHaveTextContent(
    "No distinct feasible first action was found",
  );
  expect(screen.queryByText("Selected first action")).not.toBeInTheDocument();
});

it("shows the first vice and bench order when alternatives differ only in lineup decisions", () => {
  const data = view();
  data.information_review!.candidates[0]!.first_lineup = {
    starting_xi: Array.from({ length: 11 }, (_, i) => `Starter ${i + 1}`),
    captain: "Starter 1",
    vice_captain: "Starter 3",
    bench: ["Reserve keeper", "First substitute", "Second substitute", "Third substitute"],
  };
  render(
    <LanguageProvider initialLanguage="en">
      <InformationReview view={data} />
    </LanguageProvider>,
  );
  const region = screen.getByTestId("information-review");
  expect(region).toHaveTextContent("Vice-captain: Starter 3");
  expect(region).toHaveTextContent(
    "Bench order: Reserve keeper → First substitute → Second substitute → Third substitute",
  );
  expect(isAdvicePayload(data)).toBe(true);
  data.information_review!.candidates[0]!.first_lineup.bench.pop();
  expect(isAdvicePayload(data)).toBe(false);
});

it.each([3, 5] as const)(
  "shows the future lineup for each news branch in a %s-week plan",
  (window) => {
    const data = view();
    data.window = window;
    const candidate = data.information_review!.candidates[0]!;
    for (const branch of candidate.branches) {
      branch.weeks = Array.from({ length: window - 1 }, (_, index) => ({
        ...branch.weeks[0]!,
        gameweek: 3 + index,
        lineup: {
          starting_xi: Array.from(
            { length: 11 },
            (_, player) => `${branch.state} week ${index} player ${player}`,
          ),
          captain: `${branch.state} captain ${index}`,
          vice_captain: `${branch.state} vice ${index}`,
          bench: [`keeper ${index}`, `first ${index}`, `second ${index}`, `third ${index}`],
        },
      }));
    }
    expect(isAdvicePayload(data)).toBe(true);
    render(
      <LanguageProvider initialLanguage="en">
        <InformationReview view={data} />
      </LanguageProvider>,
    );
    for (const branch of candidate.branches) {
      const summary = screen.getByText(
        branch.state === "eligible"
          ? "If eligibility is confirmed"
          : "If unavailability is confirmed",
      );
      fireEvent.click(summary);
      const section = summary.closest("details")!;
      for (const week of branch.weeks) {
        const detail = within(section).getByTestId(`week-lineup-${week.gameweek}`);
        fireEvent.click(within(detail).getByText(/This week's starting eleven and bench/));
        expect(detail).toHaveAttribute("open");
        expect(detail).toHaveTextContent(week.lineup!.starting_xi.join(", "));
        expect(detail).toHaveTextContent(`Vice-captain: ${week.lineup!.vice_captain}`);
        expect(detail).toHaveTextContent(week.lineup!.bench.join(" → "));
      }
    }
    candidate.branches[0]!.weeks[0]!.lineup!.starting_xi.pop();
    expect(isAdvicePayload(data)).toBe(false);
  },
);
