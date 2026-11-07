/**
 * Who a typed text names among a league's members: a part of a manager's or team's name,
 * without case or accents, or the team number the game gives, for two members of one name.
 */

import type { RosterEntry } from "../identity/useLeagueIdentity";

/** A name as typed and as listed compare without case or accents: "sukru" finds "Şükrü". */
function plain(value: string | null): string {
  return (value ?? "")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .replace(/ı/g, "i")
    .toLocaleLowerCase("en");
}

/**
 * The rows the typed text leaves: by name (manager or team, any part), or, as the game's
 * own team number when the text is digits only, by that number. Nothing typed keeps every
 * row.
 */
export function matchingMembers(
  rows: readonly RosterEntry[],
  typed: string,
): readonly RosterEntry[] {
  const query = typed.trim();
  if (query === "") return rows;
  if (/^\d+$/.test(query)) {
    const entryId = Number(query);
    return rows.filter((row) => row.entryId === entryId);
  }
  const needle = plain(query);
  return rows.filter(
    (row) => plain(row.managerName).includes(needle) || plain(row.teamName).includes(needle),
  );
}
