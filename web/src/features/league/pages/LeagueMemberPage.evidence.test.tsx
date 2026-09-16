/**
 * The switched-on document shows the club's own words beside the plan: the category the
 * model coded, the role the declared rule gave it, the words cut from the captured bytes
 * with their source, and the price against the pure-points pick. Example data is said to
 * be example data on the section itself. Nothing on it reads as a probability.
 */

import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import type { EntryAdvice, EntryAdviceIndex, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;

function switchedOn(overrides: Partial<EntryAdvice> = {}): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
  return {
    ...base,
    payload: {
      ...base.payload,
      expected_points_cost: 1.25,
      expected_points_cost_ceiling: 1.25,
      solver_status: "OPTIMAL",
      control_solver_status: "OPTIMAL",
      evidence: {
        kind: "managers_word",
        rule_version: "managers_word_rule_v1",
        source_kind: "synthetic_fixture",
        source_label: "club_news_v1.fixture.json",
        evidence_table: "rotation_evidence_v2_2026-27_gw05.csv",
        clubs_covered: ["Arsenal"],
        applied: [
          {
            player_id: 5001,
            name: "Kai Havertz",
            disposition: "stated_expected_absent",
            role: "not_starting",
            speaker: "the manager",
            published_at_utc: "2026-09-11T14:00:00Z",
            published_precision: "instant",
            club: "Arsenal",
            source_url: "https://club.example/arsenal/news",
            fetched_at_utc: "2026-09-12T14:05:00Z",
            words: "Havertz will not travel.",
          },
        ],
      },
      ...overrides,
    },
  };
}

const INDEX: EntryAdviceIndex = {
  ...mockEntryAdviceIndex(ENTRY).payload,
  evidence: {
    available: true,
    path: `advice/${ENTRY}/saf-puan/1/hoca-sozu.json`,
    applied_count: 1,
    source_kind: "synthetic_fixture",
    source_label: "club_news_v1.fixture.json",
    clubs_covered: ["Arsenal"],
    rule_version: "managers_word_rule_v1",
  },
};

function renderPage(language: Language, advice: LeagueViewEnvelope<EntryAdvice>) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}?mode=saf-puan&window=1&llm=on`]}>
        <LeagueMemberView
          squad={mockEntrySquadEnvelopes[ENTRY]}
          advice={advice}
          members={mockLeagueMembersEnvelope.payload.members}
          index={INDEX}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("the manager's word on the advice card", () => {
  it("shows the words, the role, the source and the price, in Turkish", () => {
    const { container } = renderPage("tr", switchedOn());
    const section = container.querySelector('[data-testid="managers-word"]');
    expect(section).not.toBeNull();
    const text = section?.textContent ?? "";
    expect(text).toContain("Kulübün sayfası ne dedi");
    expect(text).toContain("Havertz will not travel.");
    expect(text).toContain("On birin dışında");
    expect(text).toContain("yok denildi");
    expect(text).toContain("Örnek veri");
    const link = section?.querySelector("a[href='https://club.example/arsenal/news']");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(container.textContent).toMatch(/1,3|1\.3/);
  });

  it("says when the word bound nothing, in English", () => {
    const advice = switchedOn();
    advice.payload.evidence = { ...advice.payload.evidence!, applied: [] };
    advice.payload.expected_points_cost = 0;
    advice.payload.expected_points_cost_ceiling = 0;
    const { container } = renderPage("en", advice);
    const text = container.querySelector('[data-testid="managers-word"]')?.textContent ?? "";
    expect(text).toContain("What the club's page said");
    expect(text).toContain("switching the word on changed nothing");
  });

  it("renders no section on a document solved without the word", () => {
    const { container } = renderPage("tr", mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
    expect(container.querySelector('[data-testid="managers-word"]')).toBeNull();
  });

  it("carries no probability wording in either language", () => {
    for (const language of ["tr", "en"] as const) {
      const { container, unmount } = renderPage(language, switchedOn());
      expect(container.textContent ?? "").not.toMatch(AS_A_CHANCE);
      unmount();
    }
  });
});
