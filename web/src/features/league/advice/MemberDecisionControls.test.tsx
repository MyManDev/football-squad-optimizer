/**
 * The member's controls name only what the producer computed: the catalogue's
 * strategies, the league's rivals with the producer's default marked, and the windows
 * the index lists — pure points at three and five weeks where this publish solved them,
 * one week for a rival strategy. Everything else is shown disabled with its reason,
 * never hidden.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import type { EntryAdviceIndex } from "../types";
import { MemberDecisionControls } from "./MemberDecisionControls";

afterEach(cleanup);

const MEMBERS = mockLeagueMembersEnvelope.payload.members;
const ENTRY = 35249001;

function Selection() {
  const [params] = useSearchParams();
  return (
    <output data-testid="selection">
      {params.get("mode") ?? "-"}/{params.get("window") ?? "-"}/{params.get("rival") ?? "-"}
    </output>
  );
}

function renderControls(
  initial = `/league/members/${ENTRY}`,
  index: EntryAdviceIndex | null = mockEntryAdviceIndex(ENTRY).payload,
  language: "tr" | "en" = "tr",
) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemoryRouter initialEntries={[initial]}>
        <MemberDecisionControls entryId={ENTRY} members={MEMBERS} index={index} />
        <Selection />
      </MemoryRouter>
    </LanguageProvider>,
  );
}

describe("member decision controls", () => {
  it("offers the three member strategies and writes the choice to the URL", () => {
    renderControls();
    expect(screen.getByDisplayValue("saf-puan")).toBeChecked();
    expect(screen.queryByRole("combobox")).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: /Ortak çekirdeği koru/ }));

    expect(screen.getByTestId("selection").textContent).toBe("ortak-koru/-/-");
    expect(screen.getByRole("combobox", { name: "Karşısında oynadığın üye" })).toBeInTheDocument();
  });

  it("marks the producer's default rival and drops the parameter when it is chosen again", () => {
    const index = mockEntryAdviceIndex(ENTRY).payload;
    const other = index.rival_entry_ids.find((id) => id !== index.default_rival_entry_id)!;
    renderControls(`/league/members/${ENTRY}?mode=fark-yarat`);

    const select = screen.getByRole("combobox", { name: "Karşısında oynadığın üye" });
    expect(select).toHaveValue(String(index.default_rival_entry_id));
    expect(screen.getByRole("option", { name: /\(sıralamada hemen üstün\)/ })).toBeInTheDocument();

    fireEvent.change(select, { target: { value: String(other) } });
    expect(screen.getByTestId("selection").textContent).toBe(`fark-yarat/-/${other}`);

    fireEvent.change(select, { target: { value: String(index.default_rival_entry_id) } });
    expect(screen.getByTestId("selection").textContent).toBe("fark-yarat/-/-");
  });

  it("labels a pair the producer could not compute", () => {
    const index = mockEntryAdviceIndex(ENTRY).payload;
    const missing = index.unavailable[0]!;
    renderControls(`/league/members/${ENTRY}?mode=${missing.strategy}`);
    const option = screen.getByRole("option", { name: /\(hesaplanamadı\)/ });
    expect(option).toHaveValue(String(missing.rival_entry_id));
  });

  it("enables the windows the index lists for pure points and states what they assume", () => {
    renderControls();
    expect(screen.getByRole("radio", { name: /1 hafta/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /3 hafta/ })).toBeEnabled();
    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeEnabled();
    expect(
      screen.getByText(/1\. hafta projeksiyonunu fikstür takvimi üzerinde tekrarlar/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("radio", { name: /3 hafta/ }));
    expect(screen.getByTestId("selection").textContent).toBe("-/3/-");
  });

  it("keeps a rival strategy at one week, with the reason", () => {
    renderControls(`/league/members/${ENTRY}?mode=ortak-koru`);
    expect(screen.getByRole("radio", { name: /1 hafta/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /3 hafta/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeDisabled();
    expect(screen.getByText(/rakip stratejisi hafta hafta oynanır/)).toBeInTheDocument();
  });

  it.each([
    ["no index", null],
    [
      "an index from before the windows existed",
      { ...mockEntryAdviceIndex(ENTRY).payload, windows: undefined },
    ],
    [
      "an index where a window did not solve",
      { ...mockEntryAdviceIndex(ENTRY).payload, windows: { "saf-puan": [1, 3] } },
    ],
  ] as const)("offers only the windows a publish solved: %s", (_name, index) => {
    renderControls(`/league/members/${ENTRY}`, index as EntryAdviceIndex | null, "en");
    expect(screen.getByRole("radio", { name: /1 week/ })).toBeEnabled();
    expect(screen.getByRole("radio", { name: /5 weeks/ })).toBeDisabled();
    if (index?.windows?.["saf-puan"]?.includes(3)) {
      expect(screen.getByRole("radio", { name: /3 weeks/ })).toBeEnabled();
    } else {
      expect(screen.getByRole("radio", { name: /3 weeks/ })).toBeDisabled();
      expect(screen.getByText(/only where this publish solved them/)).toBeInTheDocument();
    }
  });

  it("falls back to the league's members as rivals when no index was published", () => {
    renderControls(`/league/members/${ENTRY}?mode=ortak-koru`, null, "en");
    const select = screen.getByRole("combobox", { name: "The member you are playing against" });
    const humans = MEMBERS.filter((m) => m.member_kind === "human" && m.entry_id !== ENTRY);
    expect(screen.getAllByRole("option")).toHaveLength(humans.length);
    expect(select).toHaveValue(String(humans[0]!.entry_id));
  });

  it("labels the declared rule's pick without preselecting it", () => {
    const base = mockEntryAdviceIndex(ENTRY).payload;
    const index: EntryAdviceIndex = {
      ...base,
      suggested_strategy: {
        ...base.suggested_strategy!,
        strategy: "fark-yarat",
        band: "behind",
        points_ahead_of_rival: -140,
      },
    };
    renderControls(`/league/members/${ENTRY}`, index, "en");

    const marked = screen.getByRole("radio", { name: /Create a gap.*The rule's pick/s });
    expect(marked).not.toBeChecked();
    // The rule marks; the URL still chooses. Nothing was selected on the member's behalf.
    expect(screen.getByDisplayValue("saf-puan")).toBeChecked();
    expect(screen.getByText(/A declared rule marks one option/)).toBeInTheDocument();
    // The two inputs the rule read are on the page, so the member can check it.
    expect(screen.getByText(/\(-140\)/)).toBeInTheDocument();
    expect(screen.getByText(/37 gameweeks still to play/)).toBeInTheDocument();
  });

  it("says the rule is declared rather than measured, in both languages", () => {
    const claims = [
      [/written down, not measured/, /nothing has tested whether following it does better/],
      [/Kural yazılı, ölçülmüş değil/, /uymanın uymamaktan daha iyi olduğu test edilmedi/],
    ] as const;
    for (const [language, patterns] of [
      ["en", claims[0]],
      ["tr", claims[1]],
    ] as const) {
      const { container, unmount } = renderControls(
        `/league/members/${ENTRY}`,
        undefined,
        language,
      );
      const text = container.textContent ?? "";
      for (const pattern of patterns) expect(text).toMatch(pattern);
      unmount();
    }
  });

  it("shows no rule label when the producer could not state one", () => {
    const base = mockEntryAdviceIndex(ENTRY).payload;
    renderControls(`/league/members/${ENTRY}`, { ...base, suggested_strategy: null }, "en");
    expect(screen.queryByText(/A declared rule marks one option/)).toBeNull();
    expect(screen.queryByText("The rule's pick")).toBeNull();
  });

  it("never shows a probability or a chance, in either language", () => {
    for (const language of ["tr", "en"] as const) {
      for (const mode of ["ortak-koru", "fark-yarat", "saf-puan"] as const) {
        const { container, unmount } = renderControls(
          `/league/members/${ENTRY}?mode=${mode}`,
          undefined,
          language,
        );
        const text = container.textContent ?? "";
        // The rule's label is on the page for this sweep, not merely available to it.
        expect(text).toMatch(/rule's pick|Kuralın seçimi/i);
        expect(text).not.toMatch(/%|probabilit|olasılık|\bP\(/i);
        expect(text).not.toMatch(/chance of falling behind|geride kalma ihtimalini/i);
        unmount();
      }
    }
  });

  it("phrases the rule as a band on the gap, never as a chance of catching up", () => {
    // The page-wide sweep above cannot carry these words: the honesty note that denies
    // probability says "chance" itself. So the rule's own copy is swept on its own, in
    // both languages, against every word that would turn a band into a likelihood.
    const AS_A_CHANCE = /chance|likelihood|odds|ihtimal|şans|yüzde|olasılık|probabilit|%/i;
    for (const language of ["tr", "en"] as const) {
      const copy = MESSAGES[language].leagueMembers;
      for (const line of [copy.rulePickBadge, copy.rulePickNote("Half Space", "-140", 37)]) {
        expect(line.length).toBeGreaterThan(0);
        expect(line).not.toMatch(AS_A_CHANCE);
      }
    }
  });
});
