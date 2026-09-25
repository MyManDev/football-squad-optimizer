import { describe, expect, it } from "vitest";

import { currentChipHalf } from "./chipShape";
import type { EntryChipAvailability } from "./types";

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
