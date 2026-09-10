import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import type { ScoreboardGameweek } from "../types";
import { ScoreboardComparisons } from "./ScoreboardComparisons";

afterEach(cleanup);

function week(settled: boolean): ScoreboardGameweek {
  return {
    gameweek: 2,
    deadline_utc: "2026-08-28T17:30:00Z",
    finished: settled,
    data_checked: settled,
    average_entry_score: null,
    highest_score: null,
    ours: null,
    top100: null,
    members: [],
    members_mean_net: null,
    members_counted: 0,
    comparisons: [
      {
        kind: "system",
        net: 47.5,
        scoring_basis: "named_eleven_no_autosubs",
        source_snapshot_id: "s",
        diagnostics: {
          zero_minute_starters: 0,
          minutes_shortfall: null,
          captain_shortfall: -2.5,
          autosub_recovery: null,
        },
      },
      {
        kind: "base",
        net: null,
        scoring_basis: null,
        source_snapshot_id: null,
        diagnostics: {
          zero_minute_starters: null,
          minutes_shortfall: null,
          captain_shortfall: null,
          autosub_recovery: null,
        },
      },
    ],
  };
}

describe.each<Language>(["en", "tr"])("scoreboard comparisons in %s", (language) => {
  it("distinguishes measured zero from missing and labels legacy scoring", () => {
    const { container } = render(
      <LanguageProvider initialLanguage={language}>
        <ScoreboardComparisons weeks={[week(true)]} />
      </LanguageProvider>,
    );
    expect(screen.getAllByRole("row")).toHaveLength(3);
    expect(container.textContent).toContain(language === "tr" ? "47,5" : "47.5");
    expect(container.textContent).toContain(language === "tr" ? "0,0" : "0.0");
    expect(container.textContent).toContain("—");
    expect(container.textContent).toContain(language === "tr" ? "ikinci kaptan" : "vice-captain");
    expect(container.textContent).not.toMatch(/probab|olasılık|yüzde|ihtimal|şans|%/i);
  });
  it("does not display unfinished values even if a stale payload supplied them", () => {
    const { container } = render(
      <LanguageProvider initialLanguage={language}>
        <ScoreboardComparisons weeks={[week(false)]} />
      </LanguageProvider>,
    );
    expect(container.textContent).not.toMatch(/47[.,]5/);
  });
  it("labels missing records and distinguishes each member's advice", () => {
    const missing = week(true);
    missing.decision_record_status = "missing";
    missing.comparisons![0]!.net = null;
    const pending = week(false);
    pending.gameweek = 4;
    pending.comparisons = [7, 8].map((entry_id) => ({
      ...missing.comparisons![0]!,
      kind: "member_advice",
      entry_id,
    }));
    render(
      <LanguageProvider initialLanguage={language}>
        <ScoreboardComparisons weeks={[missing, pending]} />
      </LanguageProvider>,
    );
    expect(
      screen.getByText(language === "tr" ? "Karar kaydı yok" : "Decision record unavailable"),
    ).toBeTruthy();
    expect(
      screen.getByText(language === "tr" ? "Üye tavsiyesi · 7" : "Member advice · 7"),
    ).toBeTruthy();
    expect(
      screen.getAllByText(
        language === "tr" ? "Yerleşmiş sonuç bekleniyor" : "Awaiting settled results",
      ),
    ).toHaveLength(2);
  });
});
