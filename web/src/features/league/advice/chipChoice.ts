/**
 * A chip the member chooses to play this gameweek.
 *
 * The producer's planner never decides a chip: a finite window counts nothing for holding
 * one back. The member can still say "play this chip", and the producer then solves the
 * one-week pure-points plan with exactly that chip forced, once for every chip the member
 * still holds. The choice lives in the URL (`chip`), like every other control on the
 * member page, and is honoured only on the plain one-week plan (manager's word off,
 * Top 100 influence at 0) and only where the index names the file.
 */

import { CHIP_NAMES } from "../chipShape";

export type MemberChip = (typeof CHIP_NAMES)[number];

/** The URL parameter carrying the chip; absent means no chip. */
export const CHIP_PARAMETER = "chip";

export function isMemberChip(value: unknown): value is MemberChip {
  return CHIP_NAMES.some((chip) => chip === value);
}

/**
 * The chip the URL asks for. Absent is no chip. A value that is not one of the game's
 * four is reported as such (`known: false`) rather than read as no chip without a word.
 */
export function parseChip(params: URLSearchParams): { chip: MemberChip | null; known: boolean } {
  const raw = params.get(CHIP_PARAMETER);
  if (raw === null) return { chip: null, known: true };
  return isMemberChip(raw) ? { chip: raw, known: true } : { chip: null, known: false };
}

/** The one path a chosen chip's document may be read from. */
export function chipPath(entryId: number, chip: MemberChip): string {
  return `advice/${entryId}/saf-puan/1/chip-${chip}.json`;
}
