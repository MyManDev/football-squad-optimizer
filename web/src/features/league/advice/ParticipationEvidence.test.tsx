import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import type { AdviceParticipationEvidence } from "../types";
import { ParticipationEvidence } from "./ParticipationEvidence";
import { isAdvicePayload } from "./adviceShape";
import { StatementOutcomes } from "./StatementOutcomes";

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

it.each(["tr", "en"] as const)("names the multiple-fixture outcome in %s", (language) => {
  const view = {
    ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload,
    participation_evidence: {
      ...evidence,
      statement_outcomes: [
        {
          player_id: 1,
          disposition: "stated_expected_absent",
          applied: false,
          reason: "ambiguous_current_week_fixture",
          source_url: null,
          source_published_at: null,
        },
      ],
    },
  };
  expect(isAdvicePayload(view)).toBe(true);
  render(
    <LanguageProvider initialLanguage={language}>
      <StatementOutcomes view={view} />
    </LanguageProvider>,
  );
  const detail = screen.getByTestId("statement-outcomes");
  expect(detail).toHaveTextContent(
    language === "tr" ? "Bu hafta birden çok lig maçı." : "Multiple league fixtures this week.",
  );
  expect(detail).not.toHaveTextContent("ambiguous_current_week_fixture");
  expect(detail).not.toHaveTextContent(
    language === "tr" ? "gerekli koşulları sağlamadığı" : "did not meet the requirements",
  );
});

it.each(["tr", "en"] as const)(
  "accepts and explains source-specific outcomes in %s",
  (language) => {
    const view = {
      ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload,
      participation_evidence: {
        ...evidence,
        statement_outcomes: [
          {
            player_id: 1,
            disposition: "stated_expected_absent",
            applied: true,
            reason: "explicit_evidence",
            source_url: "https://www.liverpoolfc.com/news/team-update",
            source_published_at: evidence.as_of,
          },
          {
            player_id: 2,
            disposition: "stated_minutes_managed",
            applied: false,
            reason: "categorical_statement_has_no_probability",
            source_url: "javascript:alert(1)",
            source_published_at: null,
          },
        ],
      },
    };
    expect(isAdvicePayload(view)).toBe(true);
    render(
      <LanguageProvider initialLanguage={language}>
        <ParticipationEvidence view={view} />
      </LanguageProvider>,
    );
    const detail = screen.getByTestId("statement-outcomes");
    expect(detail).toHaveTextContent(
      language === "tr" ? "Açık yokluk haberi uygulandı" : "explicit absence statement was applied",
    );
    expect(detail).toHaveTextContent(
      language === "tr"
        ? "sayısal değişiklik için yeterli değil"
        : "cannot supply a numerical adjustment",
    );
    expect(detail.querySelectorAll("a")).toHaveLength(1);
    expect(detail.querySelector("a")).toHaveAttribute(
      "href",
      "https://www.liverpoolfc.com/news/team-update",
    );
    expect(detail).not.toHaveTextContent("categorical_statement_has_no_probability");
    expect(
      isAdvicePayload({
        ...view,
        participation_evidence: {
          ...view.participation_evidence,
          statement_outcomes: [
            { ...view.participation_evidence.statement_outcomes[0], raw_quote: "private" },
          ],
        },
      }),
    ).toBe(false);
  },
);

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
    expect(detail).not.toHaveTextContent(
      language === "tr" ? "ilk 11 garantisi sayılmaz" : "do not guarantee a start",
    );
    expect(detail).not.toHaveTextContent(
      language === "tr" ? "tek başına tahmini değiştirmez" : "do not change the forecast",
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

it.each(["tr", "en"] as const)(
  "says which of three things left nothing applied in %s",
  (language) => {
    const base = mockEntryAdviceEnvelope(101, "saf-puan", 3).payload;
    const states = [
      // Statements read, all turned away.
      {
        counts: { manager_statement_count: 3, unapplied_statement_count: 3 },
        text:
          language === "tr"
            ? "Okunan açıklamaların hiçbiri gerekli koşulları sağlamadı; tahmin değişmedi."
            : "None of the statements read met the requirements; the forecast is unchanged.",
      },
      // Statements read, some not turned away, and still none reached a player.
      {
        counts: { manager_statement_count: 3, unapplied_statement_count: 1 },
        text:
          language === "tr"
            ? "Bu tahmine uygulanmış hoca açıklaması yok."
            : "No coach statement was applied to this forecast.",
      },
      // Nothing read.
      {
        counts: { manager_statement_count: 0, unapplied_statement_count: 0 },
        text:
          language === "tr"
            ? "Bu hafta değerlendirilecek hoca açıklaması okunmadı."
            : "No coach statement was read for this week.",
      },
    ];
    const sentences = states.map((state) => state.text);
    for (const state of states) {
      const view = {
        ...base,
        participation_evidence: { ...evidence, applied_player_count: 0, ...state.counts },
      };
      const { unmount } = render(
        <LanguageProvider initialLanguage={language}>
          <ParticipationEvidence view={view} />
        </LanguageProvider>,
      );
      const detail = screen.getByTestId("participation-evidence");
      expect(detail).toHaveTextContent(state.text);
      for (const other of sentences.filter((sentence) => sentence !== state.text)) {
        expect(detail).not.toHaveTextContent(other);
      }
      unmount();
    }
  },
);

it.each(["tr", "en"] as const)(
  "separates source availability records from no applied coach news and names the evidence context in %s",
  (language) => {
    const view = {
      ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload,
      participation_evidence: {
        ...evidence,
        applied_player_count: 0,
        manager_statement_count: 0,
        unapplied_statement_count: 0,
      },
    };
    render(
      <LanguageProvider initialLanguage={language}>
        <ParticipationEvidence view={view} />
      </LanguageProvider>,
    );
    const detail = screen.getByTestId("participation-evidence");
    expect(detail).not.toHaveAttribute("open");
    expect(detail).toHaveTextContent(
      language === "tr"
        ? "Kontrol edilen FPL oynayabilirlik kaydı: 5"
        : "FPL availability records checked: 5",
    );
    expect(detail).toHaveTextContent(
      language === "tr" ? "Değerlendirilen hoca açıklaması: 0" : "Coach statements considered: 0",
    );
    // No statement was read at all: the page says that, not that none was applied.
    expect(detail).toHaveTextContent(
      language === "tr"
        ? "Bu hafta değerlendirilecek hoca açıklaması okunmadı."
        : "No coach statement was read for this week.",
    );
    expect(detail.querySelector("time")).toHaveAttribute("datetime", evidence.as_of);
    expect(detail.querySelector("time")).toHaveTextContent("UTC");
    expect(detail).toHaveTextContent(language === "tr" ? "OH6" : "GW6");
    // The forecast fixture belongs to GW2; the displayed context comes from the evidence.
    expect(view.gameweek).not.toBe(view.participation_evidence.gameweek);
  },
);

it.each([null, "not-a-date"])("does not invent a missing or invalid evidence date (%s)", (asOf) => {
  const view = {
    ...mockEntryAdviceEnvelope(101, "saf-puan", 3).payload,
    participation_evidence: { ...evidence, as_of: asOf, gameweek: null },
  };
  render(
    <LanguageProvider initialLanguage="tr">
      <ParticipationEvidence view={view} />
    </LanguageProvider>,
  );
  const detail = screen.getByTestId("participation-evidence");
  expect(detail.querySelector("time")).toBeNull();
  expect(detail).toHaveTextContent("Tarih bildirilmedi");
  expect(detail).toHaveTextContent("Hafta bildirilmedi");
  expect(detail).not.toHaveTextContent("not-a-date");
  expect(detail).not.toHaveTextContent("Bu tahmine uygulanmış hoca açıklaması yok.");
});

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
  "lists no assumption sentences for applied minute constraints in %s",
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
    expect(detail).not.toHaveTextContent(
      language === "tr" ? "daha kısa sürelere" : "learned shorter durations",
    );
    expect(detail).not.toHaveTextContent(
      language === "tr"
        ? "gol ve asist toplamı, oynayabilirlik uygulanmadan önce korunur"
        : "goal and assist totals stay fixed before eligibility is applied",
    );
    expect(detail).not.toHaveTextContent(
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
  "shows the counts for unavailable minute inputs without an assumption sentence in %s",
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
    expect(detail).not.toHaveTextContent(
      language === "tr" ? "doğrulanamadığı için uygulanmadı" : "could not be verified",
    );
    expect(detail).not.toHaveTextContent("minute_evidence_not_applied");
    expect(detail).toHaveTextContent(
      language === "tr"
        ? "Doğrulanmış haberin uygulandığı oyuncu: 0"
        : "Players with verified statements applied: 0",
    );
  },
);
