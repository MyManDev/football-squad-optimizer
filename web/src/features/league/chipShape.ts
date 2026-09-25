import type { EntryChipAvailability } from "./types";

export const CHIP_NAMES = ["wildcard", "freehit", "bboost", "3xc"] as const;
export const CHIP_HALVES = ["first_half", "second_half"] as const;

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function positive(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

export function isEntryChips(value: unknown, gameweek: number): value is EntryChipAvailability {
  if (
    !record(value) ||
    typeof value.known !== "boolean" ||
    value.gameweek !== gameweek ||
    !positive(value.gameweek) ||
    !record(value.states)
  )
    return false;
  const states = value.states;
  const names = value.known ? CHIP_NAMES : Object.keys(states);
  return names.every((chip) => {
    const halves = states[chip];
    if (
      !record(halves) ||
      !Object.keys(halves).every((key) => CHIP_HALVES.some((half) => half === key))
    )
      return false;
    return CHIP_HALVES.every((half) => {
      const window = halves[half];
      if (window === null) return true;
      if (
        !record(window) ||
        !positive(window.start_event) ||
        !positive(window.stop_event) ||
        window.stop_event < window.start_event ||
        typeof window.state !== "string" ||
        !["available", "used", "expired", "not_yet", "unknown"].includes(window.state)
      )
        return false;
      return window.state === "used"
        ? positive(window.gameweek) &&
            window.gameweek >= window.start_event &&
            window.gameweek <= window.stop_event
        : window.gameweek === null;
    });
  });
}

/**
 * The half of the season the member's chips are read in: the first half while the week the
 * chips were read for is inside any first-half window, the second half after that.
 */
export function currentChipHalf(chips: EntryChipAvailability): (typeof CHIP_HALVES)[number] {
  const firstStops = Object.values(chips.states)
    .map((halves) => halves.first_half?.stop_event)
    .filter((stop): stop is number => typeof stop === "number");
  return firstStops.length === 0 || chips.gameweek <= Math.max(...firstStops)
    ? "first_half"
    : "second_half";
}
