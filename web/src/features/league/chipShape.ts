import type {
  ChipWindowState,
  ChipWindowStateName,
  EntryChipAvailability,
  EntrySquad,
} from "./types";

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

/** A published window a page can state: the document knows which state it is in. */
export type KnownChipWindow = ChipWindowState & {
  state: Exclude<ChipWindowStateName, "unknown">;
};

export function isKnownWindow(
  window: ChipWindowState | null | undefined,
): window is KnownChipWindow {
  return window != null && window.state !== "unknown";
}

/** The member's chips where the document is well formed and knows them; null otherwise. */
export function knownChips(
  squad: Pick<EntrySquad, "chips" | "gameweek">,
): EntryChipAvailability | null {
  return isEntryChips(squad.chips, squad.gameweek) && squad.chips.known ? squad.chips : null;
}

/** The order D-Lig lists the chips in: the two squad chips, then the two points chips. */
const VIEWER_ORDER = [
  "wildcard",
  "freehit",
  "3xc",
  "bboost",
] as const satisfies readonly (typeof CHIP_NAMES)[number][];

/** The viewer's chips as the league table states them beside it. */
export interface ViewerChipLines {
  half: (typeof CHIP_HALVES)[number];
  lines: { chip: (typeof VIEWER_ORDER)[number]; window: KnownChipWindow }[];
  /** The first half is being played and no chip's second-half window has opened. */
  secondHalfClosed: boolean;
}

/**
 * The viewer's chips for the half being played, one line a chip with a known window there,
 * in D-Lig's order. Null when there is no line to state.
 */
export function viewerChipLines(
  squad: Pick<EntrySquad, "chips" | "gameweek">,
): ViewerChipLines | null {
  const chips = knownChips(squad);
  if (chips === null) return null;
  const half = currentChipHalf(chips);
  const lines = VIEWER_ORDER.flatMap((chip) => {
    const window = chips.states[chip]?.[half];
    return isKnownWindow(window) ? [{ chip, window }] : [];
  });
  if (lines.length === 0) return null;
  const secondHalfClosed =
    half === "first_half" &&
    CHIP_NAMES.every((chip) => chips.states[chip]?.second_half?.state === "not_yet");
  return { half, lines, secondHalfClosed };
}
