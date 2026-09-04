/**
 * The honesty gate as a test: no advice state, in either language, may show a
 * probability. The rival-relative window probabilities fell three pre-registered
 * calibrations and the line is closed; the copy says so, and this test keeps every
 * rendered advice state — proven, unproven, priced modes, partial data — inside the
 * envelope: expected points and price tags only, no percent signs, no P(...), no
 * "probability" in any spelling the site uses.
 */

import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { mockEntryAdviceEnvelope, mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const FORBIDDEN = /%|probabilit|olasılık|\bP\(/i; // the plan's regex, verbatim

function withAdvice(overrides: Partial<EntryAdvice>): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(35249001, "saf-puan", 1);
  return { ...base, payload: { ...base.payload, ...overrides } };
}

function renderState(language: Language, advice: LeagueViewEnvelope<EntryAdvice>): string {
  const { container, unmount } = render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={["/league/members/35249001"]}>
        <LeagueMemberView squad={mockEntrySquadEnvelopes[35249001]} advice={advice} />
      </MemoryRouter>
    </LanguageProvider>,
  );
  const text = container.textContent ?? "";
  unmount();
  return text;
}

const STATES: Array<[string, LeagueViewEnvelope<EntryAdvice>]> = [
  ["proven baseline", withAdvice({ solver_status: "OPTIMAL", optimality_gap: 0 })],
  ["unproven plan", withAdvice({ solver_status: "FEASIBLE", optimality_gap: 1.3 })],
  ["priced competitive mode", mockEntryAdviceEnvelope(35249001, "garantici", 1)],
  [
    "partial data",
    withAdvice({ data_quality: "partial", missing_fields: ["free_transfers"], moves: [] }),
  ],
  ["legacy document without solver fields", withAdvice({})],
];

describe("no advice state shows a probability, in either language", () => {
  for (const language of ["tr", "en"] as const) {
    for (const [name, advice] of STATES) {
      it(`${language}: ${name}`, () => {
        const text = renderState(language, advice);
        expect(text.length).toBeGreaterThan(0);
        const match = text.match(FORBIDDEN);
        expect(match, match ? `forbidden fragment: …${match[0]}…` : undefined).toBeNull();
      });
    }
  }
});
