/** Chip selection: an explicit chip this week, or joint automatic timing. */
import { CHIP_NAMES } from "../chipShape";

export type MemberChip = (typeof CHIP_NAMES)[number];
export type ChipSelection = MemberChip | "auto";

/** The URL parameter carrying the chip; absent means no chip. */
export const CHIP_PARAMETER = "chip";

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
