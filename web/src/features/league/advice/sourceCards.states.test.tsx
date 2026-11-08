/**
 * The source cards say what the source said, as the source said it: a value the source did
 * not state is not drawn, the central league card stays off, and the first week's eleven is
 * named as that week.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { mockInformationReview } from "../../../fixtures/information";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { EntryAdvice } from "../types";
import { InformationReview } from "./InformationReview";
import { OfficialInformationCard } from "./OfficialInformationCard";
import { isAdvicePayload } from "./adviceShape";

afterEach(cleanup);

// A member whose squad the example publishes in full, so the answer names its players.
function base(): EntryAdvice {
  return mockEntryAdviceEnvelope(35249001, "saf-puan", 3).payload;
}

function withFirstLineup(view: EntryAdvice): EntryAdvice {
  const candidate = view.information_review!.candidates[0]!;
  candidate.first_lineup = {
    starting_xi: Array.from({ length: 11 }, (_, i) => `Starter ${i + 1}`),
    captain: "Starter 1",
    vice_captain: "Starter 3",
    bench: ["Reserve keeper", "First substitute", "Second substitute", "Third substitute"],
  };
  return view;
}

function show(language: "tr" | "en", node: React.ReactElement) {
  return render(<LanguageProvider initialLanguage={language}>{node}</LanguageProvider>);
}

describe("the information review", () => {
  it("draws no playing value when the source stated none", () => {
    const view = { ...base(), information_review: mockInformationReview() };
    view.information_review!.source_playing_chance_percent = null;
    expect(isAdvicePayload(view)).toBe(true);
    show("tr", <InformationReview view={view} />);
    const region = screen.getByRole("region", { name: "Haber gelince plan nasıl değişir?" });
    expect(region).not.toHaveTextContent("FPL oynama değeri");
    expect(region).not.toHaveTextContent("/100");
    expect(region).not.toHaveTextContent("%");
    expect(region).toHaveTextContent(view.information_review!.player_name ?? "");
  });

  it.each(["tr", "en"] as const)(
    "names the first week's eleven as the decision week, in %s",
    (language) => {
      const view = withFirstLineup({ ...base(), information_review: mockInformationReview() });
      expect(isAdvicePayload(view)).toBe(true);
      show(language, <InformationReview view={view} />);
      const region = screen.getByRole("region", {
        name:
          language === "tr"
            ? "Haber gelince plan nasıl değişir?"
            : "How could news change the plan?",
      });
      const week = language === "tr" ? `OH${view.gameweek}` : `GW${view.gameweek}`;
      expect(region).toHaveTextContent(
        language === "tr" ? `İlk haftanın on biri: ${week}` : `First Week's Eleven: ${week}`,
      );
    },
  );
});

describe("the central league injury card", () => {
  it("is off in the page as it is in the producer, whatever the payload carries", () => {
    const view = {
      ...base(),
      official_injuries: {
        contract_version: "official_pl_injuries_v1",
        season: "2026-27",
        source_url: "https://www.premierleague.com/en/latest-player-injuries",
        source_updated_at: "2026-10-01T15:50:00Z",
        observed_at: "2026-10-02T10:00:00Z",
        roster_clubs: ["Liverpool"],
        received_clubs: ["Liverpool"],
        missing_clubs: [],
        incomplete_clubs: [],
        unknown_source_clubs: [],
        listed_rows: 1,
        mapped_rows: 1,
        facts: [
          {
            player_id: 10,
            club: "Liverpool",
            injury: "Ankle",
            source_date: "2026-09-20T10:00:00Z",
            details_urls: [],
          },
        ],
        limit:
          "Editorial injury rows do not establish absence, expected minutes, or complete squad health.",
      },
    };
    const { container } = show("tr", <OfficialInformationCard view={view as EntryAdvice} />);
    expect(container).not.toHaveTextContent("premierleague.com");
    expect(container).not.toHaveTextContent("Ankle");
    expect(container.querySelector('[data-testid="official-injuries"]')).toBeNull();
  });
});
