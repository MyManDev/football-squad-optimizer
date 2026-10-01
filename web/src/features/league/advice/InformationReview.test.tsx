import { mockInformationReview } from "../../../fixtures/information";
import { isAdvicePayload } from "./adviceShape";
import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { InformationReview } from "./InformationReview";
import type { EntryAdvice } from "../types";

afterEach(cleanup);
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
  expect(region).toHaveTextContent("75%");
  expect(region).toHaveTextContent("Bu hafta transfer yapma");
  expect(region).toHaveTextContent("kesin gelecek transfer tahmini değildir");
  expect(region).toHaveTextContent("Top100 ağırlığı puan kazancı değildir");
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
