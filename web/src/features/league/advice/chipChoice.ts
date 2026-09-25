/** Chip selection: an explicit chip this week, or joint automatic timing. */
import { CHIP_NAMES } from "../chipShape";

export type MemberChip = (typeof CHIP_NAMES)[number];
export type ChipSelection = MemberChip | "auto";

/** The URL parameter carrying the chip; absent means no chip. */
export const CHIP_PARAMETER = "chip";

/**
 * Whether the page offers automatic chip timing (`chip=auto`). It does not (audit
 * 2026-09-25, H3): the planner's holding value is built from the window's own weeks, so it
 * never beats the window's best week and spends the chip inside the window however much
 * of the season is left. The backend refuses `chip=auto` as well. Offer it again only once
 * the holding value comes from the captured season calendar (fixture counts and doubles),
 * and put the Automatic sentence back in `chipStrategy.note` (i18n/messages.ts) with it.
 *
 * Named chips over 3 and 5 weeks and a chip with a Top 100 setting stay offered: they
 * force the named chip this week and carry no holding value.
 */
export const AUTOMATIC_CHIP_OFFERED: boolean = false;

export function isMemberChip(value: unknown): value is MemberChip {
  return CHIP_NAMES.some((chip) => chip === value);
}

/**
 * The chip the URL asks for. Absent is no chip. A value that is not one of the game's
 * four is reported as such (`known: false`) rather than read as no chip without a word.
 */
export function parseChip(params: URLSearchParams): { chip: ChipSelection | null; known: boolean } {
  const raw = params.get(CHIP_PARAMETER);
  if (raw === null) return { chip: null, known: true };
  return raw === "auto" || isMemberChip(raw)
    ? { chip: raw, known: true }
    : { chip: null, known: false };
}

/** The one path a chosen chip's document may be read from. */
export function chipPath(entryId: number, chip: MemberChip): string {
  return `advice/${entryId}/saf-puan/1/chip-${chip}.json`;
}
