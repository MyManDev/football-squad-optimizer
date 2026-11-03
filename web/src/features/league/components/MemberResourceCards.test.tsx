import { cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import { CHIP_NAMES, isEntryChips } from "../chipShape";
import { assertSquad } from "../publicationShape";
import type { ChipWindowStateName, EntryChipAvailability } from "../types";
import { MemberResourceCards } from "./MemberResourceCards";

afterEach(cleanup);

function fixture(state: ChipWindowStateName = "available") {
  const document = structuredClone(mockEntrySquadEnvelopes[35249001]!);
  document.payload.gameweek = 4;
  document.payload.free_transfers = 3;
  document.payload.free_transfers_known = true;
  document.payload.chips = {
    known: true,
    gameweek: 4,
    states: Object.fromEntries(
      CHIP_NAMES.map((chip) => [
        chip,
        {
          first_half: {
            state,
            gameweek: state === "used" ? 3 : null,
            start_event: 1,
            stop_event: 19,
          },
          second_half: { state: "not_yet", gameweek: null, start_event: 20, stop_event: 38 },
        },
      ]),
    ) as EntryChipAvailability["states"],
  };
  return document;
}
function show(document: ReturnType<typeof fixture>, language: Language) {
  return render(
    <LanguageProvider initialLanguage={language}>
      <MemberResourceCards squad={document.payload} />
    </LanguageProvider>,
  );
}
function card(title: string) {
  return screen.getByRole("heading", { name: title }).closest("section")!;
}

describe.each<Language>(["tr", "en"])("member resource cards in %s", (language) => {
  it.each([0, 3])("shows a known transfer count, including zero (%i)", (count) => {
    const document = fixture();
    document.payload.free_transfers = count;
    show(document, language);
    expect(
      within(card(MESSAGES[language].memberResources.transfersTitle)).getByText(String(count), {
        exact: true,
      }),
    ).toBeInTheDocument();
  });
  it("draws no fallback transfer count and no available chips when unknown", () => {
    const document = fixture();
    document.payload.free_transfers_known = false;
    document.payload.chips!.known = false;
    const { container } = show(document, language);
    const copy = MESSAGES[language].memberResources;
    expect(screen.queryByRole("heading", { name: copy.transfersTitle })).toBeNull();
    expect(screen.queryByText("3", { exact: true })).toBeNull();
    expect(screen.queryByRole("heading", { name: copy.chipsTitle })).toBeNull();
    expect(screen.queryByText(copy.states.available)).toBeNull();
    expect(screen.getByText(MESSAGES[language].leagueMembers.toolEmpty)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
  });
  it("keeps each card to what the document states", () => {
    const copy = MESSAGES[language].memberResources;
    const noCount = fixture();
    noCount.payload.free_transfers_known = false;
    const { unmount } = show(noCount, language);
    expect(screen.queryByRole("heading", { name: copy.transfersTitle })).toBeNull();
    expect(card(copy.chipsTitle)).toHaveTextContent(copy.states.available);
    unmount();
    const noChips = fixture();
    noChips.payload.chips!.known = false;
    show(noChips, language);
    expect(card(copy.transfersTitle)).toHaveTextContent("3");
    expect(screen.queryByRole("heading", { name: copy.chipsTitle })).toBeNull();
  });
  it.each(["available", "used", "expired", "not_yet"] as const)(
    "renders published %s windows with their bounds and honest copy",
    (state) => {
      const { container } = show(fixture(state), language);
      const copy = MESSAGES[language].memberResources;
      expect(
        screen.getAllByText(state === "used" ? copy.used(3) : copy.states[state]),
      ).toHaveLength(state === "not_yet" ? 8 : 4);
      expect(screen.getAllByText(copy.window(1, 19))).toHaveLength(4);
      expect(screen.getAllByText(copy.window(20, 38))).toHaveLength(4);
      expect(container.textContent).not.toMatch(AS_A_CHANCE);
    },
  );
  it("accepts legacy documents and a season with only one window", () => {
    const copy = MESSAGES[language].memberResources;
    const document = fixture();
    delete document.payload.chips;
    expect(assertSquad(document, 35249001)).toBe(document);
    const { unmount } = show(document, language);
    expect(screen.queryByRole("heading", { name: copy.chipsTitle })).toBeNull();
    unmount();
    document.payload.chips = fixture().payload.chips;
    document.payload.chips!.states.freehit!.second_half = null;
    const { container } = show(document, language);
    // The window that is not there draws no row; the same chip's other window stays.
    expect(screen.getAllByText(copy.window(1, 19))).toHaveLength(4);
    expect(screen.getAllByText(copy.window(20, 38))).toHaveLength(3);
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
  });
  it("draws no row for a window whose state the document does not know", () => {
    const copy = MESSAGES[language].memberResources;
    show(fixture("unknown"), language);
    expect(screen.queryByText(copy.window(1, 19))).toBeNull();
    expect(screen.queryByText(copy.halves.first_half)).toBeNull();
    expect(screen.getAllByText(copy.window(20, 38))).toHaveLength(4);
  });
  it("leaves out a chip with no window to state, and its name", () => {
    const copy = MESSAGES[language].memberResources;
    const document = fixture();
    document.payload.chips!.states.freehit = { first_half: null, second_half: null };
    show(document, language);
    const names = MESSAGES[language].leagueMembers.chipNames;
    expect(screen.queryByRole("heading", { name: names.freehit })).toBeNull();
    expect(screen.getByRole("heading", { name: names.wildcard })).toBeInTheDocument();
    expect(card(copy.chipsTitle)).toHaveTextContent(copy.states.available);
  });
});

it.each([
  "wrong_week",
  "missing_half",
  "bad_state",
  "missing_used_week",
  "outside_window",
  "fractional_bound",
  "negative_transfers",
])("refuses malformed entry resources: %s", (failure) => {
  const document = fixture("used");
  const chips = document.payload.chips!;
  const window = chips.states.freehit!.first_half!;
  if (failure === "wrong_week") chips.gameweek++;
  if (failure === "missing_half")
    delete (chips.states.freehit as Partial<typeof chips.states.freehit>).second_half;
  if (failure === "bad_state") Object.assign(window, { state: "perhaps" });
  if (failure === "missing_used_week") window.gameweek = null;
  if (failure === "outside_window") window.gameweek = 20;
  if (failure === "fractional_bound") window.start_event = 1.5;
  if (failure === "negative_transfers") document.payload.free_transfers = -1;
  expect(() => assertSquad(document, 35249001)).toThrow();
});

it("rejects non-object chip payloads", () => {
  for (const value of [null, [], "available", { known: "true" }])
    expect(isEntryChips(value, 4)).toBe(false);
});
