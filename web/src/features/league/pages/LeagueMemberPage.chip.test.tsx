/**
 * A chip the member chose, on the advice card: which chip, what the chip week is expected
 * to score above the member's own plan without it, signed, and the sentence saying that is
 * one gameweek's difference and not advice to play the chip now. No price line: a gain is
 * never worded as something given up. A Triple Captain or Bench Boost week names the basis
 * it scores on. A document for another chip is not shown, and nothing can be computed
 * while a chip is chosen.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import {
  mockEntryAdviceChipEnvelope,
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { chipPath, type MemberChip } from "../advice/chipChoice";
import { CHIP_COPY } from "../advice/chipCopy";
import type { EntryAdvice, EntryAdviceIndex, LeagueViewEnvelope } from "../types";
import { LeagueMemberView } from "./LeagueMemberPage";

afterEach(cleanup);

const ENTRY = 35249001;
const CHIPS: MemberChip[] = ["wildcard", "freehit", "bboost", "3xc"];

const INDEX: EntryAdviceIndex = {
  ...mockEntryAdviceIndex(ENTRY).payload,
  chips: {
    available: true,
    paths: Object.fromEntries(CHIPS.map((chip) => [chip, chipPath(ENTRY, chip)])),
    unavailable: [],
    held: [...CHIPS],
  },
};

function chosen(
  chip: MemberChip,
  gain: number,
  overrides: Partial<EntryAdvice> = {},
): LeagueViewEnvelope<EntryAdvice> {
  const base = mockEntryAdviceChipEnvelope(ENTRY, chip);
  return {
    ...base,
    payload: {
      ...base.payload,
      chip_choice: { ...base.payload.chip_choice!, gain_vs_no_chip: gain },
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
  return container.querySelector('[data-testid="chip-choice"]')?.textContent ?? "";
}

describe("a chosen chip on the advice card", () => {
  it("states the chip, the signed gain and the honesty sentence, in Turkish", () => {
    const { container } = renderPage(
      "tr",
      chosen("bboost", 8.25),
      "mode=saf-puan&window=1&chip=bboost",
    );
    const text = section(container);
    expect(text).toContain(CHIP_COPY.tr.title);
    expect(text).toContain(CHIP_COPY.tr.chosen("Bench Boost"));
    expect(text).toContain(CHIP_COPY.tr.gain("+8,3"));
    expect(text).toContain(CHIP_COPY.tr.honesty);
    expect(text).toMatch(/ölçülmedi/);
    expect(text).toMatch(/tavsiyesi değildir/);
    expect(text).not.toContain(CHIP_COPY.tr.freeHit);
    const page = container.textContent ?? "";
    expect(page).toContain(CHIP_COPY.tr.limits[chosen("bboost", 0).payload.stated_limits![0]!]);
    expect(page).not.toContain(MESSAGES.tr.leagueMembers.statedLimitUnknown);
  });

  it("states the same in English, and the Free Hit's one-week squad", () => {
    const { container } = renderPage(
      "en",
      chosen("freehit", 3.48),
      "mode=saf-puan&window=1&chip=freehit",
    );
    const text = section(container);
    expect(text).toContain(CHIP_COPY.en.chosen("Free Hit"));
    expect(text).toContain(CHIP_COPY.en.gain("+3.5"));
    expect(text).toMatch(/is not measured, so this is not advice to play it now/);
    expect(text).toContain(CHIP_COPY.en.freeHit);
    const page = container.textContent ?? "";
    for (const sentence of chosen("freehit", 0).payload.stated_limits!) {
      expect(page).toContain(CHIP_COPY.en.limits[sentence]);
    }
    expect(page).not.toContain(MESSAGES.en.leagueMembers.statedLimitUnknown);
  });

  it("prints a chip week that came out below the plan without it as measured", () => {
    const { container } = renderPage(
      "en",
      chosen("wildcard", -0.42),
      "mode=saf-puan&window=1&chip=wildcard",
    );
    expect(section(container)).toContain(CHIP_COPY.en.gain("−0.4"));
  });

  it("prints no price line and no give-up wording for a gain", () => {
    for (const language of ["tr", "en"] as const) {
      const { container } = renderPage(
        language,
        chosen("3xc", 6.4, { control_solver_status: "FEASIBLE", control_optimality_gap: 0.3 }),
        "mode=saf-puan&window=1&chip=3xc",
      );
      // Every emphasised line on the card and the chip section itself: none is a price.
      const lines = [
        section(container),
        ...Array.from(container.querySelectorAll('[class*="planCost"]'), (p) => p.textContent),
      ].join(" ");
      expect(lines).not.toMatch(/gives up|give up|vazgeç|at most|en fazla/i);
      expect(lines).not.toMatch(/recommend|best week|öner|en iyi hafta/i);
      expect(container.textContent ?? "").not.toMatch(AS_A_CHANCE);
      // The control's missing proof is said in the chip section, not as a price ceiling.
      expect(container.textContent).not.toContain(
        MESSAGES[language].leagueMembers.controlUnprovenBody("0.3").slice(0, 40),
      );
      expect(section(container)).toContain(CHIP_COPY[language].unproven);
      cleanup();
    }
  });

  it("names the basis a Triple Captain and a Bench Boost week score on", () => {
    const triple = renderPage("en", chosen("3xc", 6.4), "mode=saf-puan&window=1&chip=3xc");
    const own = chosen("3xc", 6.4).payload.expected_own_points!;
    expect(triple.container.textContent).toContain(
      CHIP_COPY.en.expectedOwnPoints(own.toFixed(1), CHIP_COPY.en.basis["3xc"]),
    );
    expect(triple.container.textContent).not.toContain(
      MESSAGES.en.leagueMembers.expectedOwnPoints(own.toFixed(1)),
    );
    cleanup();

    const wildcard = renderPage(
      "en",
      chosen("wildcard", 2),
      "mode=saf-puan&window=1&chip=wildcard",
    );
    const plain = chosen("wildcard", 2).payload.expected_own_points!;
    expect(wildcard.container.textContent).toContain(
      MESSAGES.en.leagueMembers.expectedOwnPoints(plain.toFixed(1)),
    );
  });

  it("shows the chip's name in the lineup, and no chip section on the plain plan", () => {
    const { container } = renderPage(
      "en",
      chosen("bboost", 8),
      "mode=saf-puan&window=1&chip=bboost",
    );
    expect(container.textContent).toContain("Bench Boost");
    expect(container.textContent).not.toContain(MESSAGES.en.leagueMembers.chipNone);
    cleanup();
    const plain = renderPage(
      "en",
      mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1, null),
      "mode=saf-puan&window=1",
    );
    expect(plain.container.querySelector('[data-testid="chip-choice"]')).toBeNull();
  });

  it.each([
    ["another chip's document", chosen("wildcard", 2)],
    ["the plain document", mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1, null)],
    ["a document whose plan plays another chip", chosen("bboost", 2, { chip: "3xc" })],
  ])("does not show %s under the chosen chip", (_label, advice) => {
    const { container } = renderPage("en", advice, "mode=saf-puan&window=1&chip=bboost");
    expect(container.querySelector('[data-testid="chip-choice"]')).toBeNull();
    expect(container.textContent).toContain(MESSAGES.en.leagueMembers.adviceUnreadable);
  });

  it("does not show a chip document under the plain selection", () => {
    const { container } = renderPage("en", chosen("bboost", 2), "mode=saf-puan&window=1");
    expect(container.querySelector('[data-testid="chip-choice"]')).toBeNull();
  });

  it("offers no compute while a chip is chosen", () => {
    const name = MESSAGES.en.leagueMembers.computeButton;
    renderPage("en", mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1, null), "mode=saf-puan&window=1");
    expect((screen.getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(false);
    cleanup();
    renderPage("en", chosen("bboost", 8), "mode=saf-puan&window=1&chip=bboost");
    expect((screen.getByRole("button", { name }) as HTMLButtonElement).disabled).toBe(true);
  });
});
