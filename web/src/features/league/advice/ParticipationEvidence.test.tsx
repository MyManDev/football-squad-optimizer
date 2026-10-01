import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import type { AdviceParticipationEvidence } from "../types";
import { ParticipationEvidence } from "./ParticipationEvidence";
import { isAdvicePayload } from "./adviceShape";

afterEach(cleanup);
const evidence: AdviceParticipationEvidence = {
  version: "football_participation_evidence_v1",
  as_of: "2026-09-01T00:00:00Z",
  gameweek: 6,
  applied_player_count: 2,
  unapplied_statement_count: 1,
  captured_percentage_count: 5,
  manager_statement_count: 3,
  assumptions: ["source_eligibility_only", "no_start_or_minutes_reestimate"],
};

it.each(["tr", "en"] as const)(
  "explains relevant participation evidence in %s without internal audit data",
  (language) => {
    const view = {
      ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload,
      participation_evidence: evidence,
    };
    render(
      <LanguageProvider initialLanguage={language}>
        <ParticipationEvidence view={view} />
      </LanguageProvider>,
    );
    const detail = screen.getByTestId("participation-evidence");
    expect(detail).toHaveTextContent(
      language === "tr" ? "ilk 11 garantisi sayılmaz" : "do not guarantee a start",
    );
    expect(detail).toHaveTextContent(
      language === "tr" ? "Uygulanamayan açıklama: 1" : "Statements that could not be applied: 1",
    );
    expect(detail).not.toHaveTextContent("source_eligibility_only");
    expect(detail).not.toHaveTextContent(
      language === "tr" ? "gelecek hafta değerleri" : "Future-week values",
    );
  },
);

it("keeps evidence optional and rejects audit internals and invalid counts", () => {
  const view = mockEntryAdviceEnvelope(101, "saf-puan", 3).payload;
  render(
    <LanguageProvider initialLanguage="en">
      <ParticipationEvidence view={view} />
    </LanguageProvider>,
  );
  expect(screen.queryByTestId("participation-evidence")).not.toBeInTheDocument();
  expect(isAdvicePayload({ ...view, participation_evidence: evidence })).toBe(true);
  expect(
    isAdvicePayload({ ...view, participation_evidence: { ...evidence, applied_player_count: -1 } }),
  ).toBe(false);
  expect(
    isAdvicePayload({
      ...view,
      participation_evidence: { ...evidence, base_revision: "internal" },
    }),
  ).toBe(false);
});

it.each(["tr", "en"] as const)(
  "explains applied minute constraints without claiming calibrated likelihoods in %s",
  (language) => {
    const minuteEvidence: AdviceParticipationEvidence = {
      ...evidence,
      assumptions: [
        "explicit_full_match_restriction",
        "no_start_reestimate",
        "appearance_unchanged_by_minute_evidence",
        "club_attack_shares_reallocated",
        "declared_minute_intervention_not_calibration",
      ],
    };
    const view = {
      ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload,
      participation_evidence: minuteEvidence,
    };
    expect(isAdvicePayload(view)).toBe(true);
    render(
      <LanguageProvider initialLanguage={language}>
        <ParticipationEvidence view={view} />
      </LanguageProvider>,
    );
    const detail = screen.getByTestId("participation-evidence");
    expect(detail).toHaveTextContent(
      language === "tr" ? "daha kısa sürelere" : "learned shorter durations",
    );
    expect(detail).toHaveTextContent(
      language === "tr" ? "gol ve asist toplamı korunur" : "goal and assist totals stay fixed",
    );
    expect(detail).toHaveTextContent(
      language === "tr" ? "açık bir model varsayımı" : "explicit model assumption",
    );
    expect(detail).not.toHaveTextContent("explicit_full_match_restriction");
    expect(detail).not.toHaveTextContent(
      language === "tr"
        ? "süre için ayrı bir tahmin üretmez"
        : "separate forecasts of starts or minutes",
    );
  },
);

it.each(["tr", "en"] as const)(
  "explains unavailable minute inputs without presenting them as applied in %s",
  (language) => {
    const view = {
      ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload,
      participation_evidence: {
        ...evidence,
        applied_player_count: 0,
        assumptions: ["no_start_or_minutes_reestimate", "minute_evidence_not_applied"],
      },
    };
    render(
      <LanguageProvider initialLanguage={language}>
        <ParticipationEvidence view={view} />
      </LanguageProvider>,
    );
    const detail = screen.getByTestId("participation-evidence");
    expect(detail).toHaveTextContent(
      language === "tr" ? "doğrulanamadığı için uygulanmadı" : "could not be verified",
    );
    expect(detail).not.toHaveTextContent(
      language === "tr" ? "daha kısa sürelere" : "learned shorter durations",
    );
  },
);
