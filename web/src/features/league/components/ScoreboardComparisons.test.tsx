import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import type { ScoreboardComparison, ScoreboardGameweek } from "../types";
import { ScoreboardComparisons } from "./ScoreboardComparisons";

afterEach(cleanup);

function week(finished = true, checked = true): ScoreboardGameweek {
  const kinds: ScoreboardComparison["kind"][] = [
    "system",
    "base",
    "elite_xi",
    "ownership_template",
    "league_mean",
    "game_mean",
  ];
  return {
    gameweek: 2,
    deadline_utc: "2026-08-28T17:30:00Z",
    finished,
    data_checked: checked,
    average_entry_score: null,
    highest_score: null,
    ours: null,
    top100: null,
    members: [],
    members_mean_net: null,
    members_counted: 0,
    comparisons: kinds.map((kind) => ({
      kind,
      net: kind === "system" ? 47.5 : null,
      scoring_basis: kind === "system" ? "named_eleven_no_autosubs" : null,
      source_snapshot_id: null,
      diagnostics: {
        zero_minute_starters: kind === "system" ? 0 : null,
        minutes_shortfall: null,
        captain_shortfall: kind === "system" ? -2.5 : null,
        autosub_recovery: null,
      },
    })),
  };
}

describe.each<Language>(["en", "tr"])("six scoreboard comparisons in %s", (language) => {
  function show(value: ScoreboardGameweek) {
    return render(
      <LanguageProvider initialLanguage={language}>
        <ScoreboardComparisons weeks={[value]} />
      </LanguageProvider>,
    );
  }
  it("separates measured zero, missing data and scoring bases with integer starter counts", () => {
    const value = week();
    value.comparisons![0]!.diagnostics.zero_minute_starters = 2;
    value.comparisons![0]!.diagnostics.minutes_shortfall = 0;
    const { container } = show(value);
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(7);
    expect(within(rows[1]!).getAllByRole("cell")[2]).toHaveTextContent(/^2$/);
    expect(within(rows[2]!).getAllByRole("cell")[2]).toHaveTextContent(/^-$/);
    expect(container.textContent).toContain(language === "tr" ? "47,5" : "47.5");
    expect(container.textContent).toContain(language === "tr" ? "-2,5" : "-2.5");
    expect(container.textContent).toContain(language === "tr" ? "ikinci kaptan" : "vice-captain");
    expect(container.textContent).not.toMatch(/probab|olasılık|yüzde|ihtimal|şans|%/i);
    expect(container.querySelector("details")).toBeNull();
    expect(within(rows[1]!).getAllByRole("cell")[3]).toHaveTextContent(
      language === "tr" ? "0,0" : "0.0",
    );
  });
  it.each([
    [false, false],
    [true, false],
  ])("hides stale values until the week is finished and checked (%s, %s)", (finished, checked) => {
    const { container } = show(week(finished, checked));
    expect(container.textContent).not.toMatch(/47[.,]5|-2[.,]5/);
    expect(
      screen.getAllByText(
        language === "tr" ? "Yerleşmiş sonuç bekleniyor" : "Awaiting settled results",
      ),
    ).toHaveLength(6);
  });
  it("accepts legacy publications without the additive table", () => {
    const legacy = week();
    delete legacy.comparisons;
    const { container } = show(legacy);
    expect(container).toBeEmptyDOMElement();
  });
  it("does not label a recorded decision as missing when only its outcome is absent", () => {
    const value = week();
    value.comparisons![0]!.net = null;
    value.ours = {
      net: null,
      xi: null,
      hits: 0,
      projected: 50,
      mode: "live",
      scoring_basis: "named_eleven_no_autosubs",
      vice_captain_named: false,
    };
    show(value);
    expect(
      screen.queryByText(language === "tr" ? "Karar kaydı yok" : "Decision record unavailable"),
    ).not.toBeInTheDocument();
  });
  it("labels missing system records and official scoring", () => {
    const value = week();
    value.comparisons![0]!.net = null;
    const { rerender } = show(value);
    expect(
      screen.getByText(language === "tr" ? "Karar kaydı yok" : "Decision record unavailable"),
    ).toBeInTheDocument();
    value.comparisons![0]!.net = 25;
    value.comparisons![0]!.scoring_basis = "official_autosub_captain_v2";
    rerender(
      <LanguageProvider initialLanguage={language}>
        <ScoreboardComparisons weeks={[value]} />
      </LanguageProvider>,
    );
    expect(
      screen.getByText(
        language === "tr"
          ? "Resmi değişiklik ve kaptan puanlaması"
          : "Official substitutions and captain scoring",
      ),
    ).toBeInTheDocument();
  });
});
