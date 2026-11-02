import { AS_A_CHANCE } from "../../../testSupport/honesty";
/**
 * The member's controls name only what the producer computed: the catalogue's
 * strategies, the league's rivals with the producer's default marked, and the windows
 * the index lists: pure points at three and five weeks where this publish solved them,
 * one week for a rival strategy. Everything else is shown disabled, never hidden.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useSearchParams } from "react-router";
import { afterEach, describe, expect, it } from "vitest";

import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import { MEMBER_STRATEGIES, type EntryAdviceIndex } from "../types";
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
  initial = `/league/352490/members/${ENTRY}`,
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
    "states the requested minimum and maximum overlap beside the chosen strategy in %s",
    (language) => {
      const { unmount } = renderControls(
        `/league/352490/members/${ENTRY}?mode=ortak-koru`,
        mockEntryAdviceIndex(ENTRY).payload,
        language,
      );
      const shared = screen.getByText(
        MESSAGES[language].leagueMembers.strategies["ortak-koru"].short,
      );
      expect(shared).toHaveTextContent(language === "tr" ? /en az 9/ : /at least 9/);
      unmount();
      renderControls(
        `/league/352490/members/${ENTRY}?mode=fark-yarat`,
        mockEntryAdviceIndex(ENTRY).payload,
        language,
      );
      const different = screen.getByText(
        MESSAGES[language].leagueMembers.strategies["fark-yarat"].short,
      );
      expect(different).toHaveTextContent(language === "tr" ? /en fazla 5/ : /at most 5/);
    },
  );
  it("offers the three member strategies and writes the choice to the URL", () => {
    renderControls();
    expect(screen.getByDisplayValue("saf-puan")).toBeChecked();
    expect(screen.queryByRole("combobox")).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: /Farkı koru/ }));

    expect(screen.getByTestId("selection").textContent).toBe("ortak-koru/-/-");
    expect(screen.getByRole("combobox", { name: "Karşısında oynadığın üye" })).toBeInTheDocument();
  });

  it("marks the producer's default rival and drops the parameter when it is chosen again", () => {
    const index = mockEntryAdviceIndex(ENTRY).payload;
    const other = index.rival_entry_ids.find((id) => id !== index.default_rival_entry_id)!;
    renderControls(`/league/352490/members/${ENTRY}?mode=fark-yarat`);

    const select = screen.getByRole("combobox", { name: "Karşısında oynadığın üye" });
    expect(select).toHaveValue(String(index.default_rival_entry_id));
    expect(screen.getByRole("option", { name: /\(sıralamada hemen üstün\)/ })).toBeInTheDocument();

    fireEvent.change(select, { target: { value: String(other) } });
    expect(screen.getByTestId("selection").textContent).toBe(`fark-yarat/-/${other}`);

    fireEvent.change(select, { target: { value: String(index.default_rival_entry_id) } });
    expect(screen.getByTestId("selection").textContent).toBe("fark-yarat/-/-");
  });

  it("keeps a pair the producer could not compute off, under the rival's name alone", () => {
    const index = mockEntryAdviceIndex(ENTRY).payload;
    const missing = index.unavailable[0]!;
    renderControls(`/league/352490/members/${ENTRY}?mode=${missing.strategy}`);
    const option = screen
      .getAllByRole<HTMLOptionElement>("option")
      .find((candidate) => candidate.value === String(missing.rival_entry_id))!;
    expect(option).toBeDisabled();
    expect(option).not.toHaveTextContent("hesaplanamadı");
  });

  it("enables the windows the index lists for pure points, without a limits sentence", () => {
    renderControls();
    expect(screen.getByRole("radio", { name: /1 hafta/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /3 hafta/ })).toBeEnabled();
    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeEnabled();
    expect(
      screen.queryByText(/1\. hafta projeksiyonunu fikstür takvimi üzerinde tekrarlar/),
    ).toBeNull();

    fireEvent.click(screen.getByRole("radio", { name: /3 hafta/ }));
    expect(screen.getByTestId("selection").textContent).toBe("-/3/-");
  });

  it("keeps a rival strategy at one week, without stating a reason", () => {
    renderControls(`/league/352490/members/${ENTRY}?mode=ortak-koru`);
    expect(screen.getByRole("radio", { name: /1 hafta/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /3 hafta/ })).toBeDisabled();
    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeDisabled();
    expect(screen.queryByText(/rakip stratejisi hafta hafta oynanır/)).toBeNull();
  });

  it("writes a strategy change with a listed window into the shareable URL", () => {
    // Most points solved five weeks, so the radio is clickable; every rival strategy is
    // published at one week only. The window must not survive the change and leave the
    // control showing a checked radio it has just disabled.
    renderControls(`/league/352490/members/${ENTRY}?window=5`);
    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeChecked();

    fireEvent.click(screen.getByRole("radio", { name: /Farkı koru/ }));

    expect(screen.getByRole("radio", { name: /1 hafta/ })).toBeChecked();
    expect(screen.getByRole("radio", { name: /5 hafta/ })).not.toBeChecked();
    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeDisabled();
    expect(screen.getByTestId("selection").textContent).toBe("ortak-koru/1/-");
  });

  it("says nothing about a moved window when the index lists the one asked for", () => {
    renderControls(`/league/352490/members/${ENTRY}?window=5`);
    expect(screen.getByRole("radio", { name: /5 hafta/ })).toBeChecked();
    expect(screen.queryByText(/bu strateji için yayınlanmadı/)).toBeNull();
  });

  it("chooses no rival for the member when the producer named no default", () => {
    // The select used to display the first candidate while the request named none, so the
    // page demanded "a rival chosen" under a dropdown that appeared to show one.
    const index = mockEntryAdviceIndex(ENTRY).payload;
    renderControls(`/league/352490/members/${ENTRY}?mode=ortak-koru`, {
      ...index,
      default_rival_entry_id: null,
    });

    const select = screen.getByRole("combobox", { name: "Karşısında oynadığın üye" });
    expect(select).toHaveValue("");
    expect(screen.getByRole("option", { name: "Bir rakip seç" })).toBeDisabled();

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
    renderControls(`/league/352490/members/${ENTRY}`, index as EntryAdviceIndex | null, "en");
    expect(screen.getByRole("radio", { name: /1 week/ })).toBeEnabled();
    expect(screen.getByRole("radio", { name: /5 weeks/ })).toBeDisabled();
    if (index?.windows?.["saf-puan"]?.includes(3)) {
      expect(screen.getByRole("radio", { name: /3 weeks/ })).toBeEnabled();
    } else {
      expect(screen.getByRole("radio", { name: /3 weeks/ })).toBeDisabled();
      expect(screen.queryByText(/only where this publish solved them/)).toBeNull();
    }
  });

  it("offers no strategies or guessed rivals when no index was published", () => {
    renderControls(`/league/352490/members/${ENTRY}?mode=ortak-koru`, null, "en");
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
    renderControls(`/league/352490/members/${ENTRY}`, index, "en");

    const marked = screen.getByRole("radio", { name: /Close the gap.*Recommended/s });
    expect(marked).not.toBeChecked();
    // The rule marks; the URL still chooses. Nothing was selected on the member's behalf.
    expect(screen.getByDisplayValue("saf-puan")).toBeChecked();
  });

  it("shows no rule label when the producer could not state one", () => {
    const base = mockEntryAdviceIndex(ENTRY).payload;
    renderControls(`/league/352490/members/${ENTRY}`, { ...base, suggested_strategy: null }, "en");
    expect(screen.queryByText("Recommended")).toBeNull();
  });

  it("never shows a probability or a chance, in either language", () => {
    for (const language of ["tr", "en"] as const) {
      for (const mode of ["ortak-koru", "fark-yarat", "saf-puan"] as const) {
        const { container, unmount } = renderControls(
          `/league/352490/members/${ENTRY}?mode=${mode}`,
          undefined,
          language,
        );
        const text = container.textContent ?? "";
        // The rule's label is on the page for this sweep, not merely available to it.
        expect(text).toMatch(/Recommended|Önerilen/);
        expect(text).not.toMatch(AS_A_CHANCE);
        expect(text).not.toMatch(/chance of falling behind|geride kalma ihtimalini/i);
        unmount();
      }
    }
  });

  it("uses the approved plan aim without ranking the published expected-points figure", () => {
    // The approved name states an aim. Its line must not rank the published figure: the
    // solve also values the bench, while expected_own_points counts eleven plus captain.
    // On 2026-27 GW4, entry 3832237's plan publishes 46.5454 with a 7.1846 bench and its
    // ortak-koru plan publishes 46.7016 with a 4.3379 bench, both OPTIMAL and free of
    // hits. This guard preserves that distinction.
    const SUPERLATIVE = /highest|most expected|en yüksek|en iyi puan/i;
    for (const language of ["tr", "en"] as const) {
      const { short } = MESSAGES[language].leagueMembers.strategies["saf-puan"];
      expect(short.length).toBeGreaterThan(0);
      expect(short).not.toMatch(SUPERLATIVE);
      const { container, unmount } = renderControls(
        `/league/352490/members/${ENTRY}?mode=saf-puan`,
        undefined,
        language,
      );
      const text = container.textContent ?? "";
      // The sweep has a subject: this is the copy the control actually renders.
      expect(text).toContain(short);
      expect(text).not.toMatch(SUPERLATIVE);
      unmount();
    }
  });

  // The owner's names for #1005 Part D, word for word in both languages and in the
  // catalogue's strategy order. The copy is pinned here rather than read back from
  // MESSAGES, so a change to any of them fails. No slug is spelled out, so the
  // repository's slug counts stay as Part D records them.
  it.each([
    ["tr", ["En çok puan", "Farkı koru", "Farkı kapat"], "Plan süresi"],
    ["en", ["Most points", "Hold the gap", "Close the gap"], "Plan length"],
  ] as const)(
    "renders the approved strategy and plan length names in %s",
    (language, names, legend) => {
      const copy = MESSAGES[language].leagueMembers;
      expect(MEMBER_STRATEGIES.map((strategy) => copy.strategies[strategy].name)).toEqual(names);
      expect(copy.windowLegend).toBe(legend);
      renderControls(`/league/352490/members/${ENTRY}`, undefined, language);
      for (const name of names) {
        expect(screen.getByRole("radio", { name: new RegExp(`^${name}`) })).toBeInTheDocument();
      }
      expect(screen.getByRole("group", { name: legend })).toBeInTheDocument();
    },
  );

  it("renders the plan and the advanced part apart, and every input once without a part", () => {
    const count = (container: HTMLElement, name: string) =>
      container.querySelectorAll(`input[name="${name}"]`).length;
    const whole = renderControls(`/league/352490/members/${ENTRY}?mode=fark-yarat`);
    for (const name of ["strategy", "window", "llm", "top100", "chip"]) {
      expect(count(whole.container, name), name).toBeGreaterThan(0);
    }
    expect(screen.getAllByRole("combobox", { name: "Karşısında oynadığın üye" })).toHaveLength(1);
    const every = Object.fromEntries(
      ["strategy", "window", "llm", "top100", "chip"].map((name) => [
        name,
        count(whole.container, name),
      ]),
    );
    whole.unmount();

    const plan = render(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}?mode=fark-yarat`]}>
          <MemberDecisionControls
            entryId={ENTRY}
            members={MEMBERS}
            index={mockEntryAdviceIndex(ENTRY).payload}
            part="plan"
          />
        </MemoryRouter>
      </LanguageProvider>,
    );
    expect(count(plan.container, "strategy")).toBe(every.strategy);
    expect(count(plan.container, "window")).toBe(every.window);
    expect(screen.getByRole("combobox", { name: "Karşısında oynadığın üye" })).toBeInTheDocument();
    for (const name of ["llm", "top100", "chip"]) expect(count(plan.container, name)).toBe(0);
    // The plan names the choice it shows, and the chosen strategy in one short line.
    expect(screen.getByRole("heading", { name: "Plan ayarları" })).toBeInTheDocument();
    expect(screen.getByText("şu an: Farkı kapat · 1 hafta")).toBeInTheDocument();
    expect(
      screen.getByText(MESSAGES.tr.leagueMembers.strategies["fark-yarat"].short),
    ).toBeInTheDocument();
    plan.unmount();

    const advanced = render(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}?mode=fark-yarat`]}>
          <MemberDecisionControls
            entryId={ENTRY}
            members={MEMBERS}
            index={mockEntryAdviceIndex(ENTRY).payload}
            part="advanced"
          />
        </MemoryRouter>
      </LanguageProvider>,
    );
    for (const name of ["llm", "chip"]) {
      expect(count(advanced.container, name)).toBe(every[name]);
    }
    for (const name of ["strategy", "window"]) expect(count(advanced.container, name)).toBe(0);
    expect(screen.queryByRole("combobox")).toBeNull();
  });

  it("words the rule's label without a chance of catching up", () => {
    // Check the declared rule's label separately as well as the full rendered controls.
    //
    // This is the same rule as the producer's `FORBIDDEN_TEXT_PATTERN`
    // (`squadopt/application/strategies/catalog.py`), and the two are deliberately not
    // the same width. This one may match any of its words anywhere, because its only
    // subject is the copy string below, a string this repository wrote, so it never meets
    // a member-typed name and the site's own "bu yüzden" never reaches it.
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
      const line = MESSAGES[language].leagueMembers.rulePickBadge;
      expect(line.length).toBeGreaterThan(0);
      expect(line).not.toMatch(AS_A_CHANCE);
    }
  });
});

describe("the device's statement beside the publish", () => {
  // A publish that solved pure points only: no rival strategy, no rival listed.
  const plainIndex: EntryAdviceIndex = {
    ...mockEntryAdviceIndex(ENTRY).payload,
    strategies: ["saf-puan"],
    windows: { "saf-puan": [1] },
    rival_entry_ids: [],
    default_rival_entry_id: null,
    computed: [],
    unavailable: [],
  };
  const humans = MEMBERS.filter(
    (member) => member.member_kind === "human" && member.entry_id !== ENTRY,
  ).map((member) => member.entry_id as number);

  it("offers a rival strategy and every league member as its rival where the device solves them", () => {
    render(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}`]}>
          <MemberDecisionControls
            entryId={ENTRY}
            members={MEMBERS}
            index={plainIndex}
            onDevice={{
              strategies: ["saf-puan", "ortak-koru", "fark-yarat"],
              windows: [1],
              rivals: humans,
              top100Weights: [0, 20],
            }}
          />
          <Selection />
        </MemoryRouter>
      </LanguageProvider>,
    );
    const differential = screen.getByRole("radio", { name: /Farkı kapat/ });
    expect(differential).toBeEnabled();
    fireEvent.click(differential);
    // The window stays at the default one week, which the device offers.
    expect(screen.getByTestId("selection")).toHaveTextContent("fark-yarat/-/-");
    // Options are named by team, not id; the values are the ids.
    const select = screen.getByRole("combobox");
    const enabled = [...select.querySelectorAll("option")].filter((option) => !option.disabled);
    // Every member is selectable; the empty "choose a rival" entry stays beside them.
    expect(
      enabled
        .map((option) => option.value)
        .filter(Boolean)
        .map(Number),
    ).toEqual(humans);
    fireEvent.change(select, { target: { value: String(humans[0]) } });
    expect(screen.getByTestId("selection")).toHaveTextContent(`fark-yarat/-/${humans[0]}`);
  });

  it("offers the weights the device solves for the one-week pure-points plan", () => {
    render(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={[`/league/members/${ENTRY}`]}>
          <MemberDecisionControls
            entryId={ENTRY}
            members={MEMBERS}
            index={plainIndex}
            onDevice={{
              strategies: ["saf-puan"],
              windows: [1],
              rivals: [],
              top100Weights: [0, 20],
            }}
            part="top100"
          />
        </MemoryRouter>
      </LanguageProvider>,
    );
    expect(screen.getByRole("radio", { name: /^20/ })).toBeEnabled();
    expect(screen.getByRole("radio", { name: /^50/ })).toBeDisabled();
  });

  it("offers nothing beyond the publish without the device's statement", () => {
    render(
      <LanguageProvider initialLanguage="tr">
        <MemoryRouter initialEntries={[`/league/352490/members/${ENTRY}`]}>
          <MemberDecisionControls entryId={ENTRY} members={MEMBERS} index={plainIndex} />
        </MemoryRouter>
      </LanguageProvider>,
    );
    // The publish solved pure points only, so no rival strategy is on the page at all.
    expect(screen.queryByRole("radio", { name: /Farkı kapat/ })).toBeNull();
    expect(screen.queryByRole("radio", { name: /Farkı koru/ })).toBeNull();
  });
});
