import { describe, expect, it } from "vitest";

import { CHIP_NAMES, currentChipHalf, knownChips, viewerChipLines } from "./chipShape";
import type { ChipWindowState, EntryChipAvailability, EntrySquad } from "./types";

function chips(gameweek: number): EntryChipAvailability {
  return {
    known: true,
    gameweek,
    states: {
      wildcard: {
        first_half: { state: "available", gameweek: null, start_event: 2, stop_event: 19 },
        second_half: { state: "not_yet", gameweek: null, start_event: 20, stop_event: 38 },
      },
      "3xc": {
        first_half: { state: "used", gameweek: 4, start_event: 1, stop_event: 19 },
        second_half: null,
      },
    },
  };
}

describe("the half of the season the chips are read in", () => {
  it("is the first half through the last first-half window, the second after it", () => {
    expect(currentChipHalf(chips(1))).toBe("first_half");
    expect(currentChipHalf(chips(6))).toBe("first_half");
    expect(currentChipHalf(chips(19))).toBe("first_half");
    expect(currentChipHalf(chips(20))).toBe("second_half");
  });
});

const FIRST: ChipWindowState = {
  state: "available",
  gameweek: null,
  start_event: 1,
  stop_event: 19,
};
const SECOND: ChipWindowState = {
  state: "not_yet",
  gameweek: null,
  start_event: 20,
  stop_event: 38,
};

/** A document's chips: every chip in both halves, but for the ones a case changes. */
function squad(
  changed: EntryChipAvailability["states"] = {},
  gameweek = 6,
): Pick<EntrySquad, "chips" | "gameweek"> {
  const states = Object.fromEntries(
    CHIP_NAMES.map((chip) => [chip, { first_half: FIRST, second_half: SECOND }]),
  );
  return { gameweek, chips: { known: true, gameweek, states: { ...states, ...changed } } };
}

describe("the chips a page can state", () => {
  it("has none for a document that does not know them, or from before the block", () => {
    const unknowing = squad();
    unknowing.chips!.known = false;
    expect(knownChips(unknowing)).toBeNull();
    expect(viewerChipLines(unknowing)).toBeNull();
    expect(knownChips({ gameweek: 6 })).toBeNull();
    expect(viewerChipLines({ gameweek: 6 })).toBeNull();
  });

  it("lists the viewer's chips for the half being played, in the table's order", () => {
    const shown = viewerChipLines(squad())!;
    expect(shown.half).toBe("first_half");
    expect(shown.lines.map((line) => line.chip)).toEqual(["wildcard", "freehit", "3xc", "bboost"]);
    expect(shown.lines.every((line) => line.window === FIRST)).toBe(true);
  });

  it("leaves out a chip with no window in the half, or one the document does not know", () => {
    const shown = viewerChipLines(
      squad({
        freehit: { first_half: null, second_half: SECOND },
        "3xc": { first_half: { ...FIRST, state: "unknown" }, second_half: SECOND },
      }),
    )!;
    expect(shown.lines.map((line) => line.chip)).toEqual(["wildcard", "bboost"]);
  });

  it("has no lines at all when no chip has a known window in the half", () => {
    const none = { first_half: null, second_half: SECOND };
    expect(
      viewerChipLines(squad({ wildcard: none, freehit: none, bboost: none, "3xc": none })),
    ).toBeNull();
  });

  it("says the second half is closed only in the first half, and only of every chip", () => {
    expect(viewerChipLines(squad())!.secondHalfClosed).toBe(true);
    expect(
      viewerChipLines(squad({ wildcard: { first_half: FIRST, second_half: null } }))!
        .secondHalfClosed,
    ).toBe(false);
    const second = viewerChipLines(
      squad(
        {
          wildcard: {
            first_half: FIRST,
            second_half: { ...SECOND, state: "available" },
          },
        },
        20,
      ),
    )!;
    expect(second.half).toBe("second_half");
    expect(second.secondHalfClosed).toBe(false);
  });
});
