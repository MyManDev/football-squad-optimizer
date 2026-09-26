/**
 * The football model's `football_team_share_v1` forecast splits each club's goals and
 * assists before availability is applied, and the backend says so beside every answer that
 * forecast decided. The page translates that sentence like every other limit, so the
 * Turkish page never shows the producer's English and neither page shows the neutral
 * "no translation" line in its place.
 */

import { cleanup, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  FOOTBALL_SHARE_STATED_LIMIT,
  NO_CHIP_STATED_LIMIT,
  WINDOW_STATED_LIMITS,
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
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

describe("the plan states that football v1 splits attacking shares before availability", () => {
  it.each(["tr", "en"] as const)("holds a reviewed %s sentence for it", (language) => {
    const copy = MESSAGES[language].leagueMembers;
    expect(Object.hasOwn(copy.statedLimits, FOOTBALL_SHARE_STATED_LIMIT)).toBe(true);
    const sentence = copy.statedLimits[FOOTBALL_SHARE_STATED_LIMIT]!;
    expect(sentence).not.toBe(copy.statedLimitUnknown);
    // A stated mechanism, not a size: no number and no chance wording in either language.
    expect(sentence).not.toMatch(AS_A_CHANCE);
    expect(sentence).not.toMatch(/\d/);
  });

  it.each(["tr", "en"] as const)("renders it under a one-week plan in %s", (language) => {
    const copy = MESSAGES[language].leagueMembers;
    renderAdvice(withLimits(1, [NO_CHIP_STATED_LIMIT, FOOTBALL_SHARE_STATED_LIMIT]), language);

    const limits = screen.getByRole("region", { name: copy.planLimitsLabel });
    expect(listed(limits)).toEqual([
      copy.statedLimits[NO_CHIP_STATED_LIMIT],
      copy.statedLimits[FOOTBALL_SHARE_STATED_LIMIT],
    ]);
    expect(limits).not.toHaveTextContent(copy.statedLimitUnknown);
    if (language === "tr") expect(limits).not.toHaveTextContent(FOOTBALL_SHARE_STATED_LIMIT);
  });

  it.each(["tr", "en"] as const)("renders it after a window's own limits in %s", (language) => {
    const copy = MESSAGES[language].leagueMembers;
    const published = [...WINDOW_STATED_LIMITS, FOOTBALL_SHARE_STATED_LIMIT];
    renderAdvice(withLimits(3, published), language);

    const limits = screen.getByRole("region", { name: copy.windowLimitsLabel });
    expect(listed(limits)).toEqual(published.map((sentence) => copy.statedLimits[sentence]));
    if (language === "tr") expect(limits).not.toHaveTextContent(FOOTBALL_SHARE_STATED_LIMIT);
  });
});
