import { AS_A_CHANCE } from "../../../testSupport/honesty";
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
  it.each(["tr", "en"] as const)(
    "describes requested minimum and maximum overlap bounds in %s",
    (language) => {
      renderControls(`/league/members/${ENTRY}`, mockEntryAdviceIndex(ENTRY).payload, language);
      const shared = screen.getByText(
        MESSAGES[language].leagueMembers.strategies["ortak-koru"].description,
      );
      const different = screen.getByText(
        MESSAGES[language].leagueMembers.strategies["fark-yarat"].description,
      );
      expect(shared).toHaveTextContent(language === "tr" ? /en az 9/ : /at least 9/);
      expect(different).toHaveTextContent(language === "tr" ? /en fazla 5/ : /at most 5/);
      expect(shared).toHaveTextContent(
        language === "tr" ? /alt sınır düşürülebilir/ : /minimum may be lowered/,
      );
      expect(different).toHaveTextContent(
        language === "tr" ? /üst sınır yükseltilebilir/ : /maximum may be raised/,
      );
      for (const description of [shared, different]) {
        expect(description).toHaveTextContent(
          language === "tr"
            ? /yayımlanan plan uygulanan sınırı/
            : /published plan states the applied bound/,
        );
        expect(description).not.toHaveTextContent(
          /up to nine|down to five|en çok dokuz|en az beş|\bhit\b|reached|ulaştı/i,
        );
      }
    },
  );
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
    expect(option).toBeDisabled();
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

  it("writes a strategy change with a listed window into the shareable URL", () => {
    // Pure points solved five weeks, so the radio is clickable; every rival strategy is
    // published at one week only. The window must not survive the change and leave the
    // control showing a checked radio it has just disabled.
    renderControls(`/league/members/${ENTRY}?window=5`);
    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeChecked();

    fireEvent.click(screen.getByRole("radio", { name: /Ortak çekirdeği koru/ }));

    expect(screen.getByRole("radio", { name: /1 hafta/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /5 hafta/ })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeDisabled();
    expect(screen.getByTestId("selection").textContent).toBe("ortak-koru/1/-");
  });

  it("says nothing about a moved window when the index lists the one asked for", () => {
    renderControls(`/league/members/${ENTRY}?window=5`);
    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeChecked();
    expect(screen.queryByText(/bu strateji için yayınlanmadı/)).toBeNull();
  });

  it("chooses no rival for the member when the producer named no default", () => {
    // The select used to display the first candidate while the request named none, so the
    // page demanded "a rival chosen" under a dropdown that appeared to show one.
    const index = mockEntryAdviceIndex(ENTRY).payload;
    renderControls(`/league/members/${ENTRY}?mode=ortak-koru`, {
      ...index,
      default_rival_entry_id: null,
    });

    const select = screen.getByRole("combobox", { name: "Karşısında oynadığın üye" });
    expect(select).toHaveValue("");
    expect(screen.getByRole("option", { name: "Bir rakip seç" })).toBeDisabled();
    expect(screen.getByText(/sıralamada bir komşu belirlemedi/)).toBeInTheDocument();

    fireEvent.change(select, { target: { value: String(index.rival_entry_ids[0]) } });
    expect(screen.getByTestId("selection").textContent).toBe(
      `ortak-koru/-/${index.rival_entry_ids[0]}`,
    );
  });

  it.each([
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

  it("offers no strategies or guessed rivals when no index was published", () => {
    renderControls(`/league/members/${ENTRY}?mode=ortak-koru`, null, "en");
    expect(screen.queryByRole("combobox")).toBeNull();
    expect(screen.queryByDisplayValue("saf-puan")).toBeNull();
    for (const radio of screen.getAllByRole("radio")) expect(radio).toBeDisabled();
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
        expect(text).not.toMatch(
          /%|probabilit|olasılık|olasılığ|\bP\(|chance|likelihood|quantile|spread|percentage|ihtimal|şans|yüzde(?!n\b)|kantil|yayılım/i,
        );
        expect(text).not.toMatch(/chance of falling behind|geride kalma ihtimalini/i);
        unmount();
      }
    }
  });

  it("does not tell a member the pure-points plan has the highest expected points", () => {
    // A superlative nothing enforces. `expected_own_points` — the figure the member's
    // card shows — is the eleven plus the captain; the solve maximises the eleven, the
    // captain and the bench together, so the two have different maximisers. On the
    // 2026-27 GW4 capture entry 3832237's pure-points plan publishes 46.5454 with a
    // 7.1846 bench and its ortak-koru plan publishes 46.7016 with a 4.3379 bench: the
    // banded plan is higher on the number that is printed and lower on the one that was
    // optimised. The card may say what the plan is chosen on; it may not rank it.
    const SUPERLATIVE = /highest|most expected|en yüksek|en iyi puan/i;
    for (const language of ["tr", "en"] as const) {
      const { description } = MESSAGES[language].leagueMembers.strategies["saf-puan"];
      expect(description.length).toBeGreaterThan(0);
      expect(description).not.toMatch(SUPERLATIVE);
      const { container, unmount } = renderControls(
        `/league/members/${ENTRY}?mode=saf-puan`,
        undefined,
        language,
      );
      const text = container.textContent ?? "";
      // The sweep has a subject: this is the copy the control actually renders.
      expect(text).toContain(description);
      expect(text).not.toMatch(SUPERLATIVE);
      unmount();
    }
  });

  it("phrases the rule as a band on the gap, never as a chance of catching up", () => {
    // Check the declared rule separately as well as the full rendered controls.
    //
    // This is the same rule as the producer's `FORBIDDEN_TEXT_PATTERN`
    // (`squadopt/application/strategies/catalog.py`), and the two are deliberately not
    // the same width. This one may match any of its words anywhere, because its only
    // subjects are the two copy strings below — strings this repository wrote — so it
    // never meets a member-typed name and the site's own "bu yüzden" never reaches it.
    // The producer's does meet names, so there `şans` and `yüzde` are bounded on both
    // sides (Şanslı, Şansal and "Bu Yüzden" are legitimate names it must publish) while
    // `ihtimal` and `olasıl` stay stems (ihtimali, olasılığı are the forbidden word
    // inflected, not names). Do not add boundaries here to match the producer, and do
    // not drop them there to match this: each is as wide as its own subject allows.

    // The bare Turkish words are still caught here, so a copy edit cannot slip one in.
    for (const word of ["olasılık", "yüzde"]) {
      expect(word).toMatch(AS_A_CHANCE);
    }
    for (const language of ["tr", "en"] as const) {
      const copy = MESSAGES[language].leagueMembers;
      for (const line of [copy.rulePickBadge, copy.rulePickNote("Half Space", "-140", 37)]) {
        expect(line.length).toBeGreaterThan(0);
        expect(line).not.toMatch(AS_A_CHANCE);
      }
    }
  });
});
