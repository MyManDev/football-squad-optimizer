/**
 * The current model's component forecast was fitted on seasons that awarded no DEFCON
 * points, and the producer says so among the plan's limits. The site holds a reviewed
 * sentence for it in both languages; the member page does not list a plan's limits.
 */

import { cleanup, render } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  NO_CHIP_STATED_LIMIT,
  NO_DEFCON_STATED_LIMIT,
  WINDOW_STATED_LIMITS,
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;

function withLimits(window: 1 | 3, limits: string[]): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", window);
  return { ...base, payload: { ...base.payload, stated_limits: limits } };
}

function renderAdvice(advice: LeagueViewEnvelope<EntryAdvice>, language: "tr" | "en") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[`/league/members/${ENTRY}?window=${advice.payload.window}`]}>
        <LeagueMemberView
          index={mockEntryAdviceIndex(ENTRY).payload}
          squad={mockEntrySquadEnvelopes[ENTRY]}
          advice={advice}
        />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

function expectNoAssumptions(container: HTMLElement, published: readonly string[]) {
  for (const language of ["tr", "en"] as const) {
    const copy = MESSAGES[language].leagueMembers;
    expect(container).not.toHaveTextContent(
      /What this (?:plan|window) assumes|Bu (?:planın|pencerenin) varsaydıkları/,
    );
    for (const sentence of published) {
      expect(container).not.toHaveTextContent(sentence);
      if (Object.hasOwn(copy.statedLimits, sentence)) {
        expect(container).not.toHaveTextContent(copy.statedLimits[sentence]!);
      }
    }
  }
}

describe("the plan states that the current model does not forecast DEFCON", () => {
  it.each(["tr", "en"] as const)("holds a reviewed %s sentence for it", (language) => {
    const copy = MESSAGES[language].leagueMembers;
    expect(Object.hasOwn(copy.statedLimits, NO_DEFCON_STATED_LIMIT)).toBe(true);
    expect(copy.statedLimits[NO_DEFCON_STATED_LIMIT]).toMatch(/DEFCON/);
  });

  it.each(["tr", "en"] as const)("is not listed on the member page in %s", (language) => {
    const week = [NO_CHIP_STATED_LIMIT, NO_DEFCON_STATED_LIMIT];
    const one = renderAdvice(withLimits(1, week), language);
    expectNoAssumptions(one.container, week);
    cleanup();
    const window = [...WINDOW_STATED_LIMITS, NO_DEFCON_STATED_LIMIT];
    const three = renderAdvice(withLimits(3, window), language);
    expectNoAssumptions(three.container, window);
  });
});
