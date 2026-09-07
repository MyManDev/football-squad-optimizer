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

// The plan's regex plus the two words that crept past it in mode copy.
const FORBIDDEN = /%|probabilit|olasılık|\bP\(/i; // the plan's regex, verbatim
// The mode copy that used to reach the member page ("reduce the chance of falling
// behind") is not a probability claim by the regex but reads as one; it must not return.
const MODE_PROMISE = /chance of falling behind|geride kalma ihtimalini/i;

function withAdvice(overrides: Partial<EntryAdvice>): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(35249001, "saf-puan", 1);
  return { ...base, payload: { ...base.payload, ...overrides } };
}

function renderState(language: Language, advice: LeagueViewEnvelope<EntryAdvice>): string {
  const { container, unmount } = render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={["/league/members/35249001?mode=" + advice.payload.mode]}>
        <LeagueMemberView
          squad={mockEntrySquadEnvelopes[35249001]}
          advice={advice}
          members={mockLeagueMembersEnvelope.payload.members}
          index={mockEntryAdviceIndex(35249001).payload}
        />
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
  ["rival strategy: keep the shared core", mockEntryAdviceEnvelope(35249001, "ortak-koru", 1)],
  ["rival strategy: create a gap", mockEntryAdviceEnvelope(35249001, "fark-yarat", 1)],
  [
    "rival strategy on an unproven control",
    {
      ...mockEntryAdviceEnvelope(35249001, "fark-yarat", 1),
      payload: {
        ...mockEntryAdviceEnvelope(35249001, "fark-yarat", 1).payload,
        control_solver_status: "FEASIBLE",
        control_optimality_gap: 0.4,
      },
    },
  ],
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
        expect(text.match(MODE_PROMISE)).toBeNull();
      });
    }
  }
});
