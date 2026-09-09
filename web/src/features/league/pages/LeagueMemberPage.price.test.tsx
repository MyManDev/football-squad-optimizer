/**
 * What the price tag on a rival strategy is allowed to say.
 *
 * A price tag is the difference between two solved plans. Where both proofs finished it
 * is the cost, and the page says so in the words it always used. Where one did not, the
 * producer publishes the bound it measured — the most the strategy can cost — and the
 * page must state that instead, in both languages. And because a constrained plan can
 * never beat the unconstrained one, no figure the page prints may read as a giveaway.
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
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;

function rivalAdvice(overrides: Partial<EntryAdvice>): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(ENTRY, "ortak-koru", 1);
  return { ...base, payload: { ...base.payload, ...overrides } };
}

function renderText(language: Language, advice: LeagueViewEnvelope<EntryAdvice>): string {
  const { container, unmount } = render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter
        initialEntries={[
          `/league/members/${ENTRY}?mode=${advice.payload.mode}&window=${advice.payload.window}`,
        ]}
      >
        <LeagueMemberView
          squad={mockEntrySquadEnvelopes[ENTRY]}
          advice={advice}
          members={mockLeagueMembersEnvelope.payload.members}
          index={mockEntryAdviceIndex(ENTRY).payload}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
  const text = container.textContent ?? "";
  unmount();
  return text;
}

describe("a proven price reads as an exact cost", () => {
  it("keeps the sentence and the figure the page has always shown, in English", () => {
    const text = renderText("en", rivalAdvice({}));
    expect(text).toMatch(/gives up ~0\.8 expected points against the pure-points pick/);
    expect(text).not.toMatch(/at most/);
  });

  it("keeps the sentence and the figure the page has always shown, in Turkish", () => {
    const text = renderText("tr", rivalAdvice({}));
    expect(text).toMatch(/~0,8 beklenen puandan vazgeçiyor/);
    expect(text).not.toMatch(/en fazla/);
  });
});

describe("an unproven price reads as a ceiling", () => {
  // The producer's shape: the control it was priced against was found, not proved, so
  // the difference is 0.8 and the most it can cost is 0.8 + the control's bound.
  const unproven = rivalAdvice({
    control_solver_status: "FEASIBLE",
    control_optimality_gap: 1.5,
    expected_points_cost: 0.8,
    expected_points_cost_ceiling: 2.3,
    alternative_plan: {
      kind: "with_hits",
      overlap_applied: 9,
      transfer_hit_points: 8,
      expected_points_cost: 6.4,
      expected_points_cost_ceiling: 7.9,
    },
  });

  it("states the most it can cost, not the difference, in English", () => {
    const text = renderText("en", unproven);
    expect(text).toMatch(/gives up at most 2\.3 expected points against the pure-points pick/);
    expect(text).not.toMatch(/gives up ~0\.8/);
    // The plan itself, and the candidate beside it, both under the same bound.
    expect(text).toMatch(/at most 7\.9 expected points against pure points/);
    expect(text).not.toMatch(/, 6\.4 expected points against pure points/);
    expect(text).toMatch(/published as a ceiling — the most this strategy can cost/);
  });

  it("states the most it can cost, not the difference, in Turkish", () => {
    const text = renderText("tr", unproven);
    expect(text).toMatch(/en fazla 2,3 beklenen puandan vazgeçiyor/);
    expect(text).not.toMatch(/~0,8 beklenen puandan vazgeçiyor/);
    expect(text).toMatch(/maliyet en fazla 7,9 beklenen puan/);
    expect(text).toMatch(/tavan olarak yayımlanıyor/);
  });

  it("says the plan is the best one found rather than one shown to be best", () => {
    const found = rivalAdvice({
      solver_status: "FEASIBLE",
      optimality_gap: 1.1,
      expected_points_cost_ceiling: 0.8,
    });
    expect(renderText("en", found)).toMatch(/It is the best plan the search found/);
    expect(renderText("tr", found)).toMatch(/aramanın bulduğu en iyi plan/);
  });
});

describe("no price is ever rendered as a giveaway", () => {
  // A minus sign in front of a points figure would read as a strategy handing points
  // out, which no constrained plan can do. The producer cannot publish one on this
  // path; the page refuses to print one whatever it is handed.
  const GIVEAWAY = /gives up[^.]*[-−]\d|vazgeçiyor|mal olurdu/;

  for (const language of ["en", "tr"] as const) {
    it(`prints no price at all rather than a negative one (${language})`, () => {
      const text = renderText(
        language,
        rivalAdvice({
          expected_points_cost: -2,
          expected_points_cost_ceiling: -2,
          alternative_plan: {
            kind: "with_hits",
            overlap_applied: 9,
            transfer_hit_points: 8,
            expected_points_cost: -6.4,
            expected_points_cost_ceiling: -6.4,
          },
        }),
      );
      expect(text.length).toBeGreaterThan(0);
      expect(text).not.toMatch(GIVEAWAY);
      expect(text).not.toMatch(/-2\.0|−2,0|-6\.4|−6,4/);
    });
  }

  it("prints no price when a plan is unproven and carries no measured ceiling", () => {
    const legacy = rivalAdvice({ control_solver_status: "FEASIBLE", control_optimality_gap: 1.5 });
    delete (legacy.payload as { expected_points_cost_ceiling?: number })
      .expected_points_cost_ceiling;
    delete (legacy.payload.alternative_plan as { expected_points_cost_ceiling?: number })
      ?.expected_points_cost_ceiling;
    const text = renderText("en", legacy);
    expect(text).not.toMatch(/gives up/);
    expect(text).toMatch(/published as a ceiling/);
  });
});
