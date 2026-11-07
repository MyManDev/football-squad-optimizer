/**
 * The team number a visitor gives to find their own row: the game's own number, the one
 * thing about a member that is theirs alone. Names are not searched; two members can share
 * one.
 */

import type { RosterEntry } from "../identity/useLeagueIdentity";

/** The whole positive number typed, or null for anything else. */
export function teamNumberIn(typed: string): number | null {
  const trimmed = typed.trim();
  const id = Number(trimmed);
  return /^\d+$/.test(trimmed) && Number.isSafeInteger(id) && id > 0 ? id : null;
}

/** The rows carrying the sought team number: one, or none while it is not among them. */
export function rowsNumbered(
  rows: readonly RosterEntry[],
  sought: number | null,
): readonly RosterEntry[] {
  return sought === null ? rows : rows.filter((row) => row.entryId === sought);
}
