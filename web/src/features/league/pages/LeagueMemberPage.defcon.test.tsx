/**
 * The current model's component forecast was fitted on seasons that awarded no DEFCON
 * points, and the producer says so among the plan's limits. The page translates that
 * sentence like every other limit, so the Turkish page never shows the producer's English.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
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

function listed(region: HTMLElement): (string | null)[] {
  return within(region)
    .getAllByRole("listitem")
    .map((item) => item.textContent);
}

describe("the plan states that the current model does not forecast DEFCON", () => {
  it.each(["tr", "en"] as const)("holds a reviewed %s sentence for it", (language) => {
    const copy = MESSAGES[language].leagueMembers;
    expect(Object.hasOwn(copy.statedLimits, NO_DEFCON_STATED_LIMIT)).toBe(true);
    expect(copy.statedLimits[NO_DEFCON_STATED_LIMIT]).not.toBe(copy.statedLimitUnknown);
  });

  it.each(["tr", "en"] as const)("renders it under a one-week plan in %s", (language) => {
    const copy = MESSAGES[language].leagueMembers;
    renderAdvice(withLimits(1, [NO_CHIP_STATED_LIMIT, NO_DEFCON_STATED_LIMIT]), language);

    const limits = screen.getByRole("region", { name: copy.planLimitsLabel });
    expect(listed(limits)).toEqual([
      copy.statedLimits[NO_CHIP_STATED_LIMIT],
      copy.statedLimits[NO_DEFCON_STATED_LIMIT],
    ]);
    if (language === "tr") {
      expect(limits).toHaveTextContent("DEFCON");
      expect(limits).not.toHaveTextContent(NO_DEFCON_STATED_LIMIT);
      expect(limits).not.toHaveTextContent(copy.statedLimitUnknown);
    }
  });

  it.each(["tr", "en"] as const)("renders it after a window's own limits in %s", (language) => {
    const copy = MESSAGES[language].leagueMembers;
    const published = [...WINDOW_STATED_LIMITS, NO_DEFCON_STATED_LIMIT];
    renderAdvice(withLimits(3, published), language);

    const limits = screen.getByRole("region", { name: copy.windowLimitsLabel });
    expect(listed(limits)).toEqual(published.map((sentence) => copy.statedLimits[sentence]));
    if (language === "tr") expect(limits).not.toHaveTextContent(NO_DEFCON_STATED_LIMIT);
  });
});
