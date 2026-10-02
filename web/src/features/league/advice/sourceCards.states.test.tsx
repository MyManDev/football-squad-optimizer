/**
 * The source cards say what the source said, as the source said it: a value the source did
 * not state is not drawn, a day is not an instant, an unnamed player is not a number, a
 * source link says whose source it is, the central league card stays off, an absent hit is
 * not a zero, and the first week's eleven is named as that week.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { mockInformationReview } from "../../../fixtures/information";
import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { AdviceParticipationEvidence, EntryAdvice } from "../types";
import { ExpectedLineup } from "./ExpectedLineup";
import { InformationReview } from "./InformationReview";
import { OFFICIAL_INJURY_CARD_ENABLED, OfficialInformationCard } from "./OfficialInformationCard";
import { ParticipationEvidence } from "./ParticipationEvidence";
import { isAdvicePayload } from "./adviceShape";

afterEach(cleanup);

const EVIDENCE: AdviceParticipationEvidence = {
  version: "football_participation_evidence_v1",
  as_of: "2026-09-01T00:00:00Z",
  gameweek: 6,
  applied_player_count: 1,
  unapplied_statement_count: 1,
  captured_percentage_count: 5,
  manager_statement_count: 2,
  assumptions: ["source_eligibility_only"],
};

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

describe("statement outcomes", () => {
  const outcomes = (published: string | null, playerId: number) => ({
    ...base(),
    participation_evidence: {
      ...EVIDENCE,
      statement_outcomes: [
        {
          player_id: playerId,
          disposition: "stated_expected_absent",
          applied: true,
          reason: "explicit_evidence",
          source_url: "https://www.liverpoolfc.com/news/team-update",
          source_published_at: published,
        },
      ],
    },
  });

  it.each(["tr", "en"] as const)(
    "labels the source's publication instant and shows a day alone as a day in %s",
    (language) => {
      const named = base().starting_xi![0]!;
      const instant = outcomes("2026-09-01T09:30:00Z", named.player_id);
      expect(isAdvicePayload(instant)).toBe(true);
      show(language, <ParticipationEvidence view={instant} />);
      const rows = screen.getByTestId("statement-outcomes");
      expect(rows).toHaveTextContent(
        language === "tr" ? "Kaynak yayın zamanı:" : "Source published:",
      );
      expect(rows.querySelector("time")).toHaveAttribute("datetime", "2026-09-01T09:30:00Z");
      cleanup();

      // A day is a day: no clock is invented for it and it is not called an instant.
      const day = outcomes("2026-09-01", named.player_id);
      show(language, <ParticipationEvidence view={day} />);
      const dayRows = screen.getByTestId("statement-outcomes");
      expect(dayRows.querySelector("time")).toHaveAttribute("datetime", "2026-09-01");
      expect(dayRows).toHaveTextContent(
        language === "tr" ? "Kaynak yayın günü:" : "Source published on:",
      );
      expect(dayRows).not.toHaveTextContent(language === "tr" ? "yayın zamanı" : "published:");
      expect(dayRows).not.toHaveTextContent("00:00");
      expect(dayRows).not.toHaveTextContent("UTC");
      cleanup();

      // Anything else the producer did not write is not shown at all.
      const odd = outcomes("2026-09", named.player_id);
      show(language, <ParticipationEvidence view={odd} />);
      expect(screen.getByTestId("statement-outcomes").querySelector("time")).toBeNull();
    },
  );

  it.each(["tr", "en"] as const)("names whose source a link is, in %s", (language) => {
    const named = base().starting_xi![0]!;
    show(language, <ParticipationEvidence view={outcomes(null, named.player_id)} />);
    const rows = screen.getByTestId("statement-outcomes");
    const link = within(rows).getByRole("link", {
      name: language === "tr" ? `Kaynak: ${named.name}` : `Source: ${named.name}`,
    });
    expect(link).toHaveAttribute("href", "https://www.liverpoolfc.com/news/team-update");
  });

  it.each(["tr", "en"] as const)(
    "says a player the answer does not name is unnamed, in %s",
    (language) => {
      show(language, <ParticipationEvidence view={outcomes(null, 987654)} />);
      const rows = screen.getByTestId("statement-outcomes");
      expect(rows).toHaveTextContent(
        language === "tr" ? "Adı yayımlanmayan oyuncu" : "Unnamed player",
      );
      expect(rows).not.toHaveTextContent("#987654");
    },
  );
});

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
        language === "tr" ? `İlk haftanın on biri: ${week}` : `First week's eleven: ${week}`,
      );
    },
  );
});

describe("the central league injury card", () => {
  it("is off in the page as it is in the producer, whatever the payload carries", () => {
    expect(OFFICIAL_INJURY_CARD_ENABLED).toBe(false);
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

describe("the expected lineup", () => {
  it("prints no hit where the document states none, and the hit it states", () => {
    const expectation = {
      version: "expected_lineup_v1",
      expected_net_points: 42.75,
      starting_points: 38,
      autosub_points: 2.5,
      captain_bonus_points: 6,
      vice_bonus_points: 0.25,
      bench_boost_points: 0,
      assumptions: ["independent_player_week_appearances"],
    };
    const absent = { ...base(), lineup_expectation: expectation };
    delete (absent as { transfer_hit_points?: number }).transfer_hit_points;
    const first = show("tr", <ExpectedLineup view={absent as EntryAdvice} />);
    expect(first.container).not.toHaveTextContent("Transfer cezası");
    cleanup();

    const stated = { ...base(), lineup_expectation: expectation, transfer_hit_points: 4 };
    const second = show("tr", <ExpectedLineup view={stated as EntryAdvice} />);
    expect(second.container).toHaveTextContent("Transfer cezası: 4,0");
  });
});
