/**
 * The chip row is the member's own declaration: "none" and the game's four chips in one
 * row, a chip enabled where the producer solved its plan, the URL carrying the choice, and
 * the reason beside every chip that is off. A chip combines with nothing, so it and the
 * other two switches turn each other off, and the plain plan is always one click away.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import type { EntryAdviceIndex } from "../types";
import { chipPath } from "./chipChoice";
import { CHIP_COPY } from "./chipCopy";
import { MemberDecisionControls } from "./MemberDecisionControls";
import { TOP100_WEIGHTS, top100Path } from "./top100";

afterEach(cleanup);

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const ENTRY = 35249001;
const WEIGHTS = TOP100_WEIGHTS.filter((weight) => weight !== 0);

const SOLVED: EntryAdviceIndex["chips"] = {
  available: true,
  paths: {
    wildcard: chipPath(ENTRY, "wildcard"),
    bboost: chipPath(ENTRY, "bboost"),
    "3xc": chipPath(ENTRY, "3xc"),
  },
  unavailable: [{ chip: "freehit", reason: "already_played" }],
  held: ["wildcard", "bboost", "3xc"],
};

function Location() {
  return <output data-testid="location">{useLocation().search}</output>;
}

function query(): URLSearchParams {
  return new URLSearchParams(screen.getByTestId("location").textContent ?? "");
}

function renderControls(
  initial: string,
  chips: EntryAdviceIndex["chips"],
  language: "tr" | "en" = "tr",
) {
  const index: EntryAdviceIndex = {
    ...mockEntryAdviceIndex(ENTRY).payload,
    chips,
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
      word_paths: {},
      unavailable: [],
    },
  };
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[initial]}>
        <MemberDecisionControls entryId={ENTRY} members={MEMBERS} index={index} />
        <Location />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

function inputs(name: string): HTMLInputElement[] {
  return Array.from(document.querySelectorAll<HTMLInputElement>(`input[name="${name}"]`));
}

const chips = () => inputs("chip");
const chipNamed = (value: string) => chips().find((input) => input.value === value)!;

describe("the chip control", () => {
  it("offers none and the four chips in one row, and the URL follows the choice", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1`, SOLVED);
    expect(chips().map((input) => input.value)).toEqual([
      "",
      "wildcard",
      "freehit",
      "bboost",
      "3xc",
    ]);
    const row = chips()[0]!.closest("div");
    expect(chips().every((input) => input.closest("div") === row)).toBe(true);
    expect(chips()[0]!.checked).toBe(true);
    expect(screen.getByText(CHIP_COPY.tr.none)).toBeTruthy();
    for (const name of Object.values(MESSAGES.tr.leagueMembers.chipNames)) {
      expect(row!.textContent).toContain(name);
    }
    expect(document.body.textContent).toContain(CHIP_COPY.tr.plain);
    expect(document.body.textContent).toContain(CHIP_COPY.tr.help);

    fireEvent.click(chipNamed("bboost"));
    expect(query().get("chip")).toBe("bboost");
    expect(chipNamed("bboost").checked).toBe(true);
    expect(document.body.textContent).toContain(CHIP_COPY.tr.chosen("Bench Boost"));
    fireEvent.click(chipNamed("3xc"));
    expect(query().get("chip")).toBe("3xc");
    fireEvent.click(chips()[0]!);
    expect(query().has("chip")).toBe(false);
    expect(chips()[0]!.checked).toBe(true);
  });

  it("turns off a chip the member cannot play, and says why", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1`, SOLVED, "en");
    expect(chipNamed("freehit").disabled).toBe(true);
    expect(chipNamed("wildcard").disabled).toBe(false);
    expect(document.body.textContent).toContain(
      CHIP_COPY.en.chipReasonLine("Free Hit", CHIP_COPY.en.chipReasons.already_played!),
    );
  });

  it("turns the manager's word and the settings above 0 off while a chip is chosen", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1&chip=wildcard`, SOLVED, "en");
    const settings = inputs("top100");
    expect(settings[0]!.disabled).toBe(false);
    expect(settings[0]!.checked).toBe(true);
    expect(settings.slice(1).every((input) => input.disabled)).toBe(true);
    expect(inputs("llm")[0]!.disabled).toBe(true);
    const notes = document.body.textContent ?? "";
    expect(notes.split(CHIP_COPY.en.switchesOff).length - 1).toBe(2);

    // One click back to the plain plan, and the other switches are live again.
    fireEvent.click(chips()[0]!);
    expect(query().has("chip")).toBe(false);
    expect(inputs("top100").every((input) => !input.disabled)).toBe(true);
    expect(inputs("llm")[0]!.disabled).toBe(false);
  });

  it.each(["top100=20", "llm=on"])(
    "turns the chips off while %s is on, and none still clears a chip left in the link",
    (other) => {
      renderControls(
        `/league/members/${ENTRY}?mode=saf-puan&window=1&chip=wildcard&${other}`,
        SOLVED,
        "en",
      );
      expect(chips()[0]!.checked).toBe(true);
      expect(chips()[0]!.disabled).toBe(false);
      expect(
        chips()
          .slice(1)
          .every((input) => input.disabled),
      ).toBe(true);
      expect(document.body.textContent).toContain(CHIP_COPY.en.blockedBySwitches);
      // The other switch is the one in force, and stays usable.
      expect(inputs("top100")[0]!.disabled).toBe(false);
      expect(inputs("llm")[0]!.disabled).toBe(false);

      fireEvent.click(chips()[0]!);
      expect(query().has("chip")).toBe(false);
      expect(query().toString()).toContain(other);
    },
  );

  it("is off on a longer window, with the note", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=3&chip=wildcard`, SOLVED, "en");
    expect(
      chips()
        .slice(1)
        .every((input) => input.disabled),
    ).toBe(true);
    expect(document.body.textContent).toContain(CHIP_COPY.en.onlyBaseline);
  });

  it("says a chip in the link that cannot be shown is not shown", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1&chip=freehit`, SOLVED, "en");
    expect(chips()[0]!.checked).toBe(true);
    expect(document.body.textContent).toContain(CHIP_COPY.en.notOffered);
  });

  it.each([
    ["chip_history_unknown", undefined],
    ["no_chip_left", [{ chip: "wildcard", reason: "already_played" }]],
    ["not_solved_for_member", undefined],
    ["a_reason_this_page_does_not_know", undefined],
  ] as const)("gives the producer's reason %s in both languages", (reason, unavailable) => {
    for (const language of ["tr", "en"] as const) {
      renderControls(
        `/league/members/${ENTRY}?mode=saf-puan&window=1`,
        { available: false, reason, ...(unavailable ? { unavailable: [...unavailable] } : {}) },
        language,
      );
      const copy = CHIP_COPY[language];
      const expected = Object.hasOwn(copy.unavailableReasons, reason)
        ? copy.unavailableReasons[reason]!
        : copy.unavailableReasons.unknown;
      expect(document.body.textContent).toContain(expected);
      expect(
        chips()
          .slice(1)
          .every((input) => input.disabled),
      ).toBe(true);
      if (unavailable) {
        expect(document.body.textContent).toContain(
          copy.chipReasonLine("Wildcard", copy.chipReasons.already_played!),
        );
      }
      cleanup();
    }
  });

  it("shows the row without a chips block at all, every chip off", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1`, undefined, "en");
    expect(chips()).toHaveLength(5);
    expect(
      chips()
        .slice(1)
        .every((input) => input.disabled),
    ).toBe(true);
    expect(document.body.textContent).toContain(CHIP_COPY.en.unavailableReasons.unknown);
  });

  it("never words the control as a chance, in either language", () => {
    for (const language of ["tr", "en"] as const) {
      renderControls(
        `/league/members/${ENTRY}?mode=saf-puan&window=1&chip=bboost`,
        SOLVED,
        language,
      );
      expect(document.body.textContent ?? "").not.toMatch(AS_A_CHANCE);
      cleanup();
    }
  });
});
