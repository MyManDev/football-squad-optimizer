/**
 * The one rival the LIVE page sets beside the member (the owner's decision of 2026-11-11):
 *
 * 1. the member `?duel=` names;
 * 2. in a head-to-head league, the member's opponent of the live week, from the league's
 *    pairings for that week (never the table's week, which runs ahead once the next week is
 *    published); a bye or the league average is no opponent;
 * 3. the member `?rival=` names;
 * 4. the published index's default (a listed league), or the member ranked just above, else
 *    just below (a forwarded league).
 *
 * An address names only a member the page holds; the picker offers the same members.
 */

import type { ForwarderResult, StandingsReason } from "../forwarder/client";
import type { FplH2hMatches } from "../forwarder/documents";
import type { EntryView } from "../types";

/** A member the picker offers. */
export interface RivalChoice {
  entryId: number;
  name: string;
}

/** The live week's opponent of a head-to-head member, as the pairings name him. */
export interface H2hOpponent {
  entryId: number;
  name: string;
}

/** At most this many pages of a week's pairings are read for the member's opponent. */
export const H2H_PAGES = 5;

/**
 * The other human members the page holds, in their order, and the opponent where they do
 * not hold him. A member without a team name is named by the manager.
 */
export function rivalChoices(
  members: readonly EntryView[],
  entryId: number,
  opponent: H2hOpponent | null,
  unnamed: string,
): RivalChoice[] {
  const choices: RivalChoice[] = [];
  for (const member of members) {
    if (member.member_kind !== "human" || member.entry_id === entryId) continue;
    choices.push({
      entryId: member.entry_id,
      name: member.team_name ?? member.manager_name ?? unnamed,
    });
  }
  if (
    opponent !== null &&
    opponent.entryId !== entryId &&
    !choices.some((choice) => choice.entryId === opponent.entryId)
  ) {
    choices.push({ entryId: opponent.entryId, name: opponent.name });
  }
  return choices;
}

const named = (value: string | null): number | null => {
  if (value === null || !/^[1-9]\d*$/.test(value)) return null;
  const id = Number(value);
  return Number.isSafeInteger(id) ? id : null;
};

const held = (id: number | null, choices: readonly RivalChoice[]) =>
  id !== null && choices.some((choice) => choice.entryId === id) ? id : null;

/** The member the address names under `key` (`duel` or `rival`), where the page holds him. */
export function addressedRival(
  search: URLSearchParams,
  key: "duel" | "rival",
  choices: readonly RivalChoice[],
): number | null {
  return held(named(search.get(key)), choices);
}

/** The rival, in the order above, among `choices`; null where there is none. */
export function chooseRival({
  search,
  opponent,
  fallback,
  choices,
}: {
  search: URLSearchParams;
  opponent: number | null;
  fallback: number | null;
  choices: readonly RivalChoice[];
}): number | null {
  return (
    addressedRival(search, "duel", choices) ??
    held(opponent, choices) ??
    addressedRival(search, "rival", choices) ??
    held(fallback, choices)
  );
}

/**
 * The member's opponent in one week's pairings, read page by page over at most
 * `H2H_PAGES` pages; null for a bye, the league average, a member the pages do not pair, or
 * a page the forwarder does not answer.
 */
export async function h2hOpponent(
  read: (page: number) => Promise<ForwarderResult<FplH2hMatches, StandingsReason>>,
  entryId: number,
): Promise<H2hOpponent | null> {
  for (let page = 1; page <= H2H_PAGES; page += 1) {
    const answer = await read(page);
    if (!answer.ok) return null;
    for (const match of answer.document.results) {
      const other =
        match.entry_1.entry === entryId
          ? match.entry_2
          : match.entry_2.entry === entryId
            ? match.entry_1
            : null;
      if (other === null) continue;
      return other.entry === null ? null : { entryId: other.entry, name: other.name };
    }
    if (!answer.document.has_next) break;
  }
  return null;
}
