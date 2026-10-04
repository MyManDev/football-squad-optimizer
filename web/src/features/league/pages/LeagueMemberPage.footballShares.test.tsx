/**
 * The football model's `football_team_share_v1` forecast splits each club's goals and
 * assists before availability is applied, and the backend says so beside every answer that
 * forecast decided. The member page does not list a plan's limits.
 */

import { cleanup, render } from "@testing-library/react";
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
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import type { EntryAdvice, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";
import { withLeague } from "../../../testSupport/league";

afterEach(cleanup);

const ENTRY = 35249001;

function withLimits(window: 1 | 3, limits: string[]): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceEnvelope(ENTRY, "saf-puan", window);
  return { ...base, payload: { ...base.payload, stated_limits: limits } };
}

function renderAdvice(advice: LeagueViewEnvelope<EntryAdvice>, language: "tr" | "en") {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter
        initialEntries={[`/league/352490/members/${ENTRY}?window=${advice.payload.window}`]}
      >
        {withLeague(
          <LeagueMemberView
            index={mockEntryAdviceIndex(ENTRY).payload}
            squad={mockEntrySquadEnvelopes[ENTRY]}
            advice={advice}
          />,
        )}
      </MemoryRouter>
    </LanguageProvider>,
  );
}

function expectNoAssumptions(container: HTMLElement, published: readonly string[]) {
  expect(container).not.toHaveTextContent(
    /What this (?:plan|window) assumes|Bu (?:planın|pencerenin) varsaydıkları/,
  );
  expect(container).not.toHaveTextContent(AS_A_CHANCE);
  for (const sentence of published) {
    expect(container).not.toHaveTextContent(sentence);
  }
}

describe("the plan states that football v1 splits attacking shares before availability", () => {
  it.each(["tr", "en"] as const)("is not listed on the member page in %s", (language) => {
    const week = [NO_CHIP_STATED_LIMIT, FOOTBALL_SHARE_STATED_LIMIT];
    const one = renderAdvice(withLimits(1, week), language);
    expectNoAssumptions(one.container, week);
    cleanup();
    const window = [...WINDOW_STATED_LIMITS, FOOTBALL_SHARE_STATED_LIMIT];
    const three = renderAdvice(withLimits(3, window), language);
    expectNoAssumptions(three.container, window);
  });
});

describe("captured football forecast limits", () => {
  const limits = [
    "Each future fixture is forecast separately from captured history; blank weeks are zero only in that week. No future outcomes or injury updates are assumed.",
    "Experimental football model; independent predictive superiority is unverified.",
    "Earlier football forecasts may already carry an absence into later weeks. This update does not restore those values without a known conditional forecast.",
  ];

  it.each(["tr", "en"] as const)("lists none on the page in %s", (language) => {
    const advice = withLimits(3, [...limits]);
    const { container } = renderAdvice(advice, language);
    expectNoAssumptions(container, limits);
    expect(advice.payload.stated_limits).toEqual(limits);
  });
});

describe("experimental football construction limits", () => {
  const limits = [
    "Complete plans are compared using expected automatic substitutions and vice-captain recovery. The limited search does not prove the best possible plan or future performance.",
    "This experimental plan compares a week-by-week starting plan with a full-window search, retaining the starting plan only after full-window validation. Future performance is not established.",
    "The week-by-week starting plan could not be completed; this result uses the standard full-window search with the remaining budget.",
  ];
  it.each(["tr", "en"] as const)("lists none on the page in %s", (language) => {
    const { container } = renderAdvice(withLimits(3, limits), language);
    expectNoAssumptions(container, limits);
  });
});
