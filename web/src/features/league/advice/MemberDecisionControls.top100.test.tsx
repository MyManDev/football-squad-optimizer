/**
 * The Top 100 influence is a horizontal row of seven settings beside the manager's word:
 * enabled where the producer solved the file, the URL carrying the choice, zero removing
 * it, and the producer's reason when nothing was solved.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import type { EntryAdviceIndex } from "../types";
import { MemberDecisionControls } from "./MemberDecisionControls";
import { TOP100_WEIGHTS, top100Path } from "./top100";
import { TOP100_COPY } from "./top100Copy";

afterEach(cleanup);

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const ENTRY = 35249001;
const WEIGHTS = TOP100_WEIGHTS.filter((weight) => weight !== 0);

const SOLVED: EntryAdviceIndex["top100"] = {
  available: true,
  published_weight: 0,
  weights: [...TOP100_WEIGHTS],
  paths: Object.fromEntries(WEIGHTS.map((w) => [String(w), top100Path(ENTRY, w, false)])),
  word_paths: {},
  unavailable: [],
};

function Location() {
  return <output data-testid="location">{useLocation().search}</output>;
}

function query(): URLSearchParams {
  return new URLSearchParams(screen.getByTestId("location").textContent ?? "");
}

function renderControls(
  initial: string,
  top100: EntryAdviceIndex["top100"],
  language: "tr" | "en" = "tr",
) {
  const index: EntryAdviceIndex = {
    ...mockEntryAdviceIndex(ENTRY).payload,
    top100,
    evidence: {
      available: true,
      path: `advice/${ENTRY}/saf-puan/1/hoca-sozu.json`,
      applied_count: 0,
      source_kind: "synthetic_fixture",
      source_label: "club_news_v1.fixture.json",
      clubs_covered: [],
      rule_version: "managers_word_rule_v1",
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

function settings(): HTMLInputElement[] {
  return Array.from(document.querySelectorAll<HTMLInputElement>('input[name="top100"]'));
}

describe("the Top 100 influence control", () => {
  it("offers seven settings in one row, and the URL follows the choice", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1`, SOLVED);
    const inputs = settings();
    expect(inputs.map((input) => input.value)).toEqual(TOP100_WEIGHTS.map(String));
    const row = inputs[0]!.closest("div");
    expect(inputs.every((input) => input.closest("div") === row)).toBe(true);
    expect(inputs.every((input) => !input.disabled)).toBe(true);
    expect(inputs[0]!.checked).toBe(true);
    expect(screen.getByText(TOP100_COPY.tr.zero)).toBeTruthy();
    expect(document.body.textContent).toContain(TOP100_COPY.tr.published);

    fireEvent.click(inputs[3]!);
    expect(query().get("top100")).toBe("20");
    expect(settings()[3]!.checked).toBe(true);
    fireEvent.click(settings()[6]!);
    expect(query().get("top100")).toBe("50");
    fireEvent.click(settings()[0]!);
    expect(query().has("top100")).toBe(false);
  });

  it("is disabled where no setting was solved for the selection, with the note", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=3&top100=20`, SOLVED, "en");
    expect(settings().every((input) => input.disabled)).toBe(true);
    expect(document.body.textContent).toContain(TOP100_COPY.en.notForSelection);
  });

  it("offers a window's and a rival strategy's settings where the index names them", () => {
    const rival = mockEntryAdviceIndex(ENTRY).payload.default_rival_entry_id!;
    const documents = [
      {
        strategy: "saf-puan",
        window: 3,
        rival_entry_id: null,
        weight: 20,
        path: `advice/${ENTRY}/saf-puan/3/top100-20.json`,
      },
      {
        strategy: "ortak-koru",
        window: 1,
        rival_entry_id: rival,
        weight: 5,
        path: `advice/${ENTRY}/ortak-koru/1/vs-${rival}/top100-5.json`,
      },
    ];
    const first = renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=3`, {
      ...SOLVED!,
      documents,
    } as EntryAdviceIndex["top100"]);
    expect(settings().map((input) => !input.disabled)).toEqual([
      true,
      false,
      false,
      true,
      false,
      false,
      false,
    ]);
    fireEvent.click(settings()[3]!);
    expect(query().get("top100")).toBe("20");
    first.unmount();
    renderControls(`/league/members/${ENTRY}?mode=ortak-koru&window=1`, {
      ...SOLVED!,
      documents,
    } as EntryAdviceIndex["top100"]);
    expect(settings().map((input) => !input.disabled)).toEqual([
      true,
      true,
      false,
      false,
      false,
      false,
      false,
    ]);
  });

  it("keeps the settings without a file for the word off while the word is on", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1&llm=on`, SOLVED);
    const inputs = settings();
    expect(inputs[0]!.disabled).toBe(false);
    expect(inputs.slice(1).every((input) => input.disabled)).toBe(true);
    expect(document.body.textContent).toContain(TOP100_COPY.tr.notSolved);
  });

  it("says why when the publish solved nothing, and never prints the code", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1`, {
      available: false,
      reason: "published_plan_carries_top100",
    });
    expect(settings().every((input) => input.disabled)).toBe(true);
    const text = document.body.textContent ?? "";
    expect(text).toContain(TOP100_COPY.tr.unavailableReasons.published_plan_carries_top100);
    expect(text).not.toContain("published_plan_carries_top100");
  });

  it("says when the link asks for a setting that is not offered, and 0 clears it", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1&top100=15`, SOLVED, "en");
    expect(document.body.textContent).toContain(TOP100_COPY.en.notOffered);
    expect(settings()[0]!.checked).toBe(true);
    fireEvent.click(settings()[0]!);
    expect(query().has("top100")).toBe(false);
    expect(document.body.textContent).not.toContain(TOP100_COPY.en.notOffered);
  });

  it("names the switches, not the menu, when the word has no file for the setting", () => {
    renderControls(`/league/members/${ENTRY}?mode=saf-puan&window=1&llm=on&top100=20`, SOLVED);
    const text = document.body.textContent ?? "";
    expect(text).toContain(TOP100_COPY.tr.notSolved);
    expect(text).not.toContain(TOP100_COPY.tr.notOffered);
  });

  it("carries no probability wording and no share of the setting, in either language", () => {
    for (const language of ["tr", "en"] as const) {
      const { container, unmount } = renderControls(
        `/league/members/${ENTRY}?mode=saf-puan&window=1&top100=30`,
        SOLVED,
        language,
      );
      expect(container.textContent ?? "").not.toMatch(AS_A_CHANCE);
      const group = screen.getByRole("group", { name: TOP100_COPY[language].legend });
      const text = group.textContent ?? "";
      expect(text).toContain(TOP100_COPY[language].help);
      expect(text).not.toMatch(/%|per\s?cent|yüzde/i);
      unmount();
    }
  });
});
