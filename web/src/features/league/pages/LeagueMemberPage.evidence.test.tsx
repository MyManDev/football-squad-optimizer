/**
 * The switched-on document shows the club's own words beside the plan: the role the
 * declared rule gave each player, the words cut from the captured bytes (or why they are
 * not shown), who said them and when, a link to the source, whether the word changed the
 * plan, and what applying it costs against the pure-points pick. Example data says so on
 * the section itself. A document that disagrees with the switch is not shown as the plan.
 * Nothing on any of it reads as a probability.
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
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { EVIDENCE_COPY } from "../advice/evidenceCopy";
import type {
  AdviceEvidenceItem,
  EntryAdvice,
  EntryAdviceIndex,
  LeagueViewEnvelope,
} from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;

function item(overrides: Partial<AdviceEvidenceItem> = {}): AdviceEvidenceItem {
  return {
    player_id: 5001,
    name: "Kai Havertz",
    disposition: "stated_expected_absent",
    role: "not_starting",
    speaker: "manager",
    published_at_utc: "2026-09-11T14:00:00Z",
    published_precision: "instant",
    club: "Arsenal",
    source_url: "https://club.example/arsenal/news",
    fetched_at_utc: "2026-09-12T14:05:00Z",
    words: "Havertz will not travel.",
    words_status: "shown",
    ...overrides,
  };
}

function switchedOn(
  applied: AdviceEvidenceItem[] = [item()],
  overrides: Partial<EntryAdvice> = {},
  sourceKind = "synthetic_fixture",
): LeagueViewEnvelope<EntryAdvice> {
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
        source_kind: sourceKind,
        source_label: "club_news_v1.fixture.json",
        evidence_table: "rotation_evidence_v2_2026-27_gw05.csv",
        clubs_covered: ["Arsenal", "Man Utd"],
        binding: true,
        applied,
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
    clubs_covered: ["Arsenal", "Man Utd"],
    rule_version: "managers_word_rule_v1",
    binding: true,
  },
};

function renderPage(
  language: Language,
  advice: LeagueViewEnvelope<EntryAdvice>,
  query = "mode=saf-puan&window=1&llm=on",
) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}?${query}`]}>
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

function sectionText(container: HTMLElement): string {
  return container.querySelector('[data-testid="managers-word"]')?.textContent ?? "";
}

describe("the manager's word on the advice card", () => {
  it("shows the words, the role, the speaker, the source, the change and the price, in Turkish", () => {
    const { container } = renderPage("tr", switchedOn());
    const section = container.querySelector('[data-testid="managers-word"]');
    expect(section).not.toBeNull();
    const text = sectionText(container);
    expect(text).toContain(EVIDENCE_COPY.tr.title);
    expect(text).toContain("Havertz will not travel.");
    expect(text).toContain(EVIDENCE_COPY.tr.roles.not_starting);
    expect(text).toContain(EVIDENCE_COPY.tr.speakers.manager);
    expect(text).not.toContain("manager,");
    expect(text).toContain(EVIDENCE_COPY.tr.changed);
    expect(text).toContain(EVIDENCE_COPY.tr.intro(2));
    expect(text).toContain(MESSAGES.tr.leagueMembers.exampleData);
    const link = section?.querySelector("a[href='https://club.example/arsenal/news']");
    expect(link?.getAttribute("rel")).toBe("noopener noreferrer");
    expect(container.textContent).toContain(EVIDENCE_COPY.tr.cost("1,3"));
  });

  it("says the word did not change the plan and still states its price, in English", () => {
    const advice = switchedOn([item({ role: "not_starting" })], {
      expected_points_cost: 0,
      expected_points_cost_ceiling: 0,
    });
    advice.payload.evidence = { ...advice.payload.evidence!, binding: false };
    const { container } = renderPage("en", advice);
    expect(sectionText(container)).toContain(EVIDENCE_COPY.en.unchanged);
    expect(container.textContent).toContain(EVIDENCE_COPY.en.cost("0.0"));
  });

  it("withholds a quote the producer withheld, and says why", () => {
    const withheld = item({ words: null, words_status: "withheld_figure", role: "not_captain" });
    const { container } = renderPage("tr", switchedOn([withheld]));
    const text = sectionText(container);
    expect(text).toContain(EVIDENCE_COPY.tr.wordsWithheld);
    expect(text).not.toContain(EVIDENCE_COPY.tr.wordsUnresolved);
    expect(text).toContain(EVIDENCE_COPY.tr.roles.not_captain);
  });

  it("links only a web address, and dates a day-only dateline to the day", () => {
    const risky = item({
      source_url: "javascript:alert(1)",
      published_at_utc: "2026-09-11T00:00:00Z",
      published_precision: "day",
      speaker: "club_statement",
    });
    const { container } = renderPage("en", switchedOn([risky]));
    const section = container.querySelector('[data-testid="managers-word"]');
    expect(section?.querySelector("a")).toBeNull();
    const text = sectionText(container);
    expect(text).toContain(EVIDENCE_COPY.en.speakers.club_statement);
    expect(text).toMatch(/11 Sept? 2026/);
    expect(text).not.toContain("00:00");
  });

  it("labels a real club-news read as such, without the example badge", () => {
    const { container } = renderPage("tr", switchedOn([item()], {}, "club_news_capture"));
    const text = sectionText(container);
    expect(text).toContain(EVIDENCE_COPY.tr.sourceCapture);
    expect(text).not.toContain(MESSAGES.tr.leagueMembers.exampleData);
  });

  it("captions a move the word caused, and only that move", () => {
    const player = (id: number, name: string) => ({
      player_id: id,
      name,
      short_name: name,
      team: "Arsenal",
      position: "MID" as const,
      expected_points: 4,
    });
    const moves = [
      {
        move_id: "gw05-1",
        player_out: player(1, "Out One"),
        player_in: player(2, "In One"),
        expected_points_delta: 1.5,
        reason_code: "manager_word" as const,
      },
      {
        move_id: "gw05-2",
        player_out: player(3, "Out Two"),
        player_in: player(4, "In Two"),
        expected_points_delta: 0.5,
        reason_code: "points_gain" as const,
      },
    ];
    const advice = switchedOn([item()], { moves, expected_gain_vs_hold: 2 });
    const { container } = renderPage("en", advice);
    const text = container.textContent ?? "";
    expect(text).toContain(EVIDENCE_COPY.en.moveReason);
    expect(text).toContain(MESSAGES.en.leagueMembers.pointsGainReason);
    expect(text.split(EVIDENCE_COPY.en.moveReason).length - 1).toBe(1);
    expect(text).not.toMatch(AS_A_CHANCE);
  });

  it("withholds a quote the page itself would not show, even if the file says shown", () => {
    const spelled = item({ words: "He is fifty per cent fit.", words_status: "shown" });
    const { container } = renderPage("en", switchedOn([spelled]));
    const text = sectionText(container);
    expect(text).toContain(EVIDENCE_COPY.en.wordsWithheld);
    expect(text).not.toContain("per cent");
  });

  it("does not show a plan without evidence as the switched-on plan", () => {
    const { container } = renderPage("tr", mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
    expect(container.querySelector('[data-testid="managers-word"]')).toBeNull();
    expect(container.textContent).not.toContain(EVIDENCE_COPY.tr.cost("0,0"));
  });

  it("does not show a switched-on plan when the switch is off", () => {
    const { container } = renderPage("tr", switchedOn(), "mode=saf-puan&window=1");
    expect(container.querySelector('[data-testid="managers-word"]')).toBeNull();
  });

  it("carries no probability wording in either language", () => {
    for (const language of ["tr", "en"] as const) {
      const withheld = item({ player_id: 5002, words: null, words_status: "withheld_figure" });
      const { container, unmount } = renderPage(language, switchedOn([item(), withheld]));
      expect(container.textContent ?? "").not.toMatch(AS_A_CHANCE);
      unmount();
    }
  });
});

describe("the manager's word and the rest of the page", () => {
  it("says nothing about change when the document does not say whether the word bound", () => {
    const advice = switchedOn();
    const { binding: _binding, ...rest } = advice.payload.evidence!;
    advice.payload.evidence = rest;
    const { container } = renderPage("en", advice);
    const text = sectionText(container);
    expect(text).not.toContain(EVIDENCE_COPY.en.changed);
    expect(text).not.toContain(EVIDENCE_COPY.en.unchanged);
  });

  it("offers no computation while the club's word is switched on", () => {
    const { container } = renderPage("en", switchedOn());
    expect(container.textContent).toContain(MESSAGES.en.leagueMembers.computeUnsupportedSelection);
  });
});
