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
  it("does not reveal a fallback transfer count or available chips when unknown", () => {
    const document = fixture();
    document.payload.free_transfers_known = false;
    document.payload.chips!.known = false;
    const { container } = show(document, language);
    const copy = MESSAGES[language].memberResources;
    expect(card(copy.transfersTitle)).toHaveTextContent(copy.unknown);
    expect(within(card(copy.transfersTitle)).queryByText("3", { exact: true })).toBeNull();
    expect(card(copy.chipsTitle)).toHaveTextContent(copy.chipsMissing);
    expect(card(copy.chipsTitle)).not.toHaveTextContent(copy.states.available);
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
  });
  it.each<ChipWindowStateName>(["available", "used", "expired", "not_yet", "unknown"])(
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
    const document = fixture();
    delete document.payload.chips;
    expect(assertSquad(document, 35249001)).toBe(document);
    const { unmount } = show(document, language);
    expect(screen.getByText(MESSAGES[language].memberResources.chipsMissing)).toBeInTheDocument();
    unmount();
    document.payload.chips = fixture().payload.chips;
    document.payload.chips!.states.freehit!.second_half = null;
    const { container } = show(document, language);
    expect(screen.getByText(MESSAGES[language].memberResources.noWindow)).toBeInTheDocument();
    expect(container.textContent).not.toMatch(AS_A_CHANCE);
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
