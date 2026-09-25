/**
 * A Top 100 weighted plan on the advice card: the setting the member chose, whether it
 * moved the plan, one price in base-model points (at most, when a proof is missing), the
 * pair's price when the manager's word is on too, the moves the setting caused, and the
 * limit read back in the member's language. A document for another setting is not shown.
 */

import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceIndex,
  mockEntryAdviceTop100Envelope,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { EVIDENCE_COPY } from "../advice/evidenceCopy";
import { TOP100_WEIGHTS, top100Path } from "../advice/top100";
import { TOP100_COPY } from "../advice/top100Copy";
import type { EntryAdvice, EntryAdviceIndex, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;
const WEIGHTS = TOP100_WEIGHTS.filter((weight) => weight !== 0);

const INDEX: EntryAdviceIndex = {
  ...mockEntryAdviceIndex(ENTRY).payload,
  evidence: {
    available: true,
    path: `advice/${ENTRY}/saf-puan/1/hoca-sozu.json`,
    applied_count: 0,
    source_kind: "synthetic_fixture",
    source_label: "club_news_v1.fixture.json",
    clubs_covered: [],
    rule_version: "managers_word_rule_v1",
  },
  top100: {
    available: true,
    published_weight: 0,
    weights: [...TOP100_WEIGHTS],
    paths: Object.fromEntries(WEIGHTS.map((w) => [String(w), top100Path(ENTRY, w, false)])),
    word_paths: Object.fromEntries(WEIGHTS.map((w) => [String(w), top100Path(ENTRY, w, true)])),
    unavailable: [],
  },
};

function weighted(
  weight: number,
  word = false,
  overrides: Partial<EntryAdvice> = {},
): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceTop100Envelope(ENTRY, weight, word);
  return {
    ...base,
    payload: {
      ...base.payload,
      expected_points_cost: 0.44,
      expected_points_cost_ceiling: 0.44,
      ...overrides,
    },
  };
}

function renderPage(language: Language, advice: LeagueViewEnvelope<EntryAdvice>, query: string) {
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

function section(container: HTMLElement): string {
  return container.querySelector('[data-testid="top100-influence"]')?.textContent ?? "";
}

describe("a Top 100 weighted plan on the advice card", () => {
  it("states the setting, the change and one price, in Turkish", () => {
    const { container } = renderPage(
      "tr",
      weighted(20, false, {
        top100: { ...weighted(20).payload.top100!, changed: true },
      }),
      "mode=saf-puan&window=1&top100=20",
    );
    const text = section(container);
    expect(text).toContain(TOP100_COPY.tr.weightLine(20));
    expect(text).toContain(TOP100_COPY.tr.changed);
    expect(text).toContain(TOP100_COPY.tr.honesty);
    expect(text).toContain(TOP100_COPY.tr.notStart);
    const page = container.textContent ?? "";
    expect(page).toContain(TOP100_COPY.tr.cost("0,4"));
    expect(page).not.toContain(TOP100_COPY.tr.costAtMost("0,4"));
    expect(page).toContain(TOP100_COPY.tr.limit(20));
    expect(page).not.toContain(MESSAGES.tr.leagueMembers.statedLimitUnknown);
  });

  it("says an unchanged plan is unchanged, in English", () => {
    const { container } = renderPage(
      "en",
      weighted(5, false, {
        expected_points_cost: 0,
        expected_points_cost_ceiling: 0,
        top100: { ...weighted(5).payload.top100!, changed: false },
      }),
      "mode=saf-puan&window=1&top100=5",
    );
    expect(section(container)).toContain(TOP100_COPY.en.unchanged);
    expect(container.textContent).toContain(TOP100_COPY.en.cost("0.0"));
  });

  it("states only the ceiling when a proof is missing, and says why", () => {
    const { container } = renderPage(
      "en",
      weighted(30, false, {
        solver_status: "FEASIBLE",
        optimality_gap: null,
        expected_points_cost: 1.7,
        expected_points_cost_ceiling: 1.7,
      }),
      "mode=saf-puan&window=1&top100=30",
    );
    const page = container.textContent ?? "";
    expect(page).toContain(TOP100_COPY.en.costAtMost("1.7"));
    expect(page).not.toContain(TOP100_COPY.en.cost("1.7"));
    expect(page).toContain(TOP100_COPY.en.unproven);
    expect(page).not.toContain(MESSAGES.en.leagueMembers.unprovenPlanGapUnknown);
  });

  it("states no price when the plan it is measured against is unproven", () => {
    // The producer publishes no ceiling then; an older document carries one, which
    // bounds nothing, so the page prints neither it nor the difference, and does not
    // promise a price below.
    const { container } = renderPage(
      "en",
      weighted(30, false, {
        solver_status: "FEASIBLE",
        optimality_gap: null,
        control_solver_status: "FEASIBLE",
        control_optimality_gap: 2.5,
        expected_points_cost: 0.2,
        expected_points_cost_ceiling: 2.7,
      }),
      "mode=saf-puan&window=1&top100=30",
    );
    const page = container.textContent ?? "";
    expect(page).not.toContain(TOP100_COPY.en.costAtMost("2.7"));
    expect(page).not.toContain(TOP100_COPY.en.cost("0.2"));
    expect(page).not.toContain(TOP100_COPY.en.unproven);
    expect(page).toContain(MESSAGES.en.leagueMembers.unprovenPlanGapUnknown);
    expect(page).toContain(MESSAGES.en.leagueMembers.controlUnprovenBody("2.5"));
  });

  it("prices the word and the setting together when both are on", () => {
    const { container } = renderPage(
      "tr",
      weighted(40, true),
      "mode=saf-puan&window=1&top100=40&llm=on",
    );
    const page = container.textContent ?? "";
    expect(page).toContain(TOP100_COPY.tr.combinedCost("0,4"));
    expect(page).not.toContain(TOP100_COPY.tr.cost("0,4"));
    expect(page).not.toContain(EVIDENCE_COPY.tr.cost("0,4"));
    expect(container.querySelector('[data-testid="managers-word"]')).not.toBeNull();
    expect(section(container)).toContain(TOP100_COPY.tr.weightLine(40));
  });

  it("captions a move the setting caused", () => {
    const base = weighted(50);
    const player = (id: number, name: string) => ({
      player_id: id,
      name,
      short_name: name,
      team: "Arsenal",
      position: "MID" as const,
      expected_points: 4,
    });
    const { container } = renderPage(
      "en",
      weighted(50, false, {
        moves: [
          {
            move_id: "gw05-1",
            player_out: player(1, "Out One"),
            player_in: player(2, "In One"),
            expected_points_delta: -0.3,
            reason_code: "top100_preference",
          },
        ],
        expected_gain_vs_hold: -0.3,
        top100: { ...base.payload.top100!, changed: true },
      }),
      "mode=saf-puan&window=1&top100=50",
    );
    expect(container.textContent).toContain(TOP100_COPY.en.moveReason);
  });

  it("prices a strategy and the setting together, and reads the window's limits back", () => {
    const base = mockEntryAdviceIndex(ENTRY).payload;
    const rival = base.default_rival_entry_id!;
    const target = { strategy: "ortak-koru", window: 3, rivalEntryId: rival };
    const advice = mockEntryAdviceTop100Envelope(ENTRY, 20, false, target);
    advice.payload = {
      ...advice.payload,
      expected_points_cost: 12.5,
      expected_points_cost_ceiling: 12.5,
      solver_status: "FEASIBLE",
      optimality_gap: null,
      control_solver_status: "OPTIMAL",
      stated_limits: [
        "The band against the rival, the overlap and the expected gap are the first week's, reached with one transfer; the later weeks are planned for points alone, because the rival's later squads are not known.",
        "The plan was chosen with the Top 100 influence at 20; every expected-points number in this document is the base model's, without it.",
        "The Top 100 counts are the previous gameweek's and are repeated over every week of the window; they are read again when the next gameweek's selections are in.",
      ],
    };
    const path = `advice/${ENTRY}/ortak-koru/3/vs-${rival}`;
    const index: EntryAdviceIndex = {
      ...INDEX,
      windows: { ...base.windows, "ortak-koru": [1, 3] },
      computed: [
        ...base.computed,
        { strategy: "ortak-koru", rival_entry_id: rival, path: `${path}.json` },
      ],
      top100: {
        ...(INDEX.top100 as Extract<EntryAdviceIndex["top100"], { available: true }>),
        documents: [
          {
            strategy: "ortak-koru",
            window: 3,
            rival_entry_id: rival,
            weight: 20,
            path: `${path}/top100-20.json`,
          },
        ],
      },
    };
    const { container } = render(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter
          initialEntries={[`/league/members/${ENTRY}?mode=ortak-koru&window=3&top100=20`]}
        >
          <LeagueMemberView
            squad={mockEntrySquadEnvelopes[ENTRY]}
            advice={advice}
            members={mockLeagueMembersEnvelope.payload.members}
            index={index}
          />
        </MemoryRouter>
      </LanguageProvider>,
    );
    const page = container.textContent ?? "";
    expect(page).toContain(TOP100_COPY.tr.strategyCostAtMost("12,5"));
    expect(page).not.toContain(TOP100_COPY.tr.strategyCost("12,5"));
    expect(page).toContain(TOP100_COPY.tr.limit(20));
    for (const sentence of Object.values(TOP100_COPY.tr.variantLimits)) {
      expect(page).toContain(sentence);
    }
    expect(page).not.toContain(MESSAGES.tr.leagueMembers.statedLimitUnknown);
    expect(section(container)).toContain(TOP100_COPY.tr.weightLine(20));
    expect(page).not.toMatch(AS_A_CHANCE);
  });

  it("does not show a document for another setting as this one", () => {
    const { container } = renderPage("en", weighted(20), "mode=saf-puan&window=1&top100=30");
    expect(section(container)).toBe("");
    expect(container.textContent).not.toContain(TOP100_COPY.en.weightLine(20));
  });

  it("does not show a weighted document as the published plan", () => {
    const { container } = renderPage("en", weighted(20), "mode=saf-puan&window=1");
    expect(section(container)).toBe("");
  });

  it("carries no probability wording and no share of the setting, in either language", () => {
    for (const language of ["tr", "en"] as const) {
      for (const [advice, query] of [
        [weighted(20), "mode=saf-puan&window=1&top100=20"],
        [weighted(20, true), "mode=saf-puan&window=1&top100=20&llm=on"],
        [
          weighted(30, false, { solver_status: "FEASIBLE", expected_points_cost_ceiling: 2 }),
          "mode=saf-puan&window=1&top100=30",
        ],
      ] as const) {
        const { container, unmount } = renderPage(language, advice, query);
        expect(container.textContent ?? "").not.toMatch(AS_A_CHANCE);
        // The squad beside the card may show an ownership share; the setting never is one.
        expect(section(container)).not.toMatch(/%|per\s?cent|yüzde/i);
        for (const price of container.querySelectorAll("p")) {
          if (price.textContent?.includes("Top 100")) {
            expect(price.textContent).not.toMatch(/%|per\s?cent|yüzde/i);
          }
        }
        unmount();
      }
    }
  });
});
