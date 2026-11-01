/**
 * The forwarded pages' reads (#983 step 4): a classic league's standings, page by page from
 * the FPL forwarder. Each spreads the league feature's read policy.
 */

import { useInfiniteQuery } from "@tanstack/react-query";

import { standings, type ForwarderReason, type StandingsReason } from "../forwarder/client";
import {
  MAX_STANDINGS_PAGE,
  type FplLeagueStandings,
  type FplStandingRow,
} from "../forwarder/documents";
import { LEAGUE_READ } from "../queries";

/** The forwarded reads' cache keys, each naming its league. */
export const forwardedKeys = {
  standings: (leagueId: number) => ["fpl-standings", leagueId] as const,
};

/** A forwarder read that gave no document, carried as the read's error. */
export class ForwarderRefused extends Error {
  readonly reason: ForwarderReason;

  constructor(reason: ForwarderReason) {
    super(`The forwarder gave no document: ${reason}.`);
    this.name = "ForwarderRefused";
    this.reason = reason;
  }
}

/**
 * What a league page 1 refusal means to the visitor: a head-to-head league, an id FPL does
 * not have as a classic league, or a forwarder that cannot answer now.
 */
export type LeagueRefusal = "head_to_head" | "unknown" | "unavailable";

export function leagueRefusal(reason: StandingsReason | ForwarderReason): LeagueRefusal {
  if (reason === "head_to_head_league") return "head_to_head";
  if (reason === "league_not_found" || reason === "not_found" || reason === "page_not_found") {
    return "unknown";
  }
  return "unavailable";
}

/** Why a read that failed failed, as a forwarder reason; `network` for anything else. */
export function refusalOf(error: unknown): ForwarderReason {
  return error instanceof ForwarderRefused ? error.reason : "network";
}

/**
 * A classic league's standings as the visitor scrolls: page 1 first, then each next page
 * while FPL says there is one, up to the forwarder's twentieth. The league gate reads page 1
 * through this same read, so the table under it starts from the page the gate opened.
 * `leagueId` null reads nothing.
 */
export function useForwardedStandings(leagueId: number | null) {
  return useInfiniteQuery({
    queryKey: forwardedKeys.standings(leagueId ?? 0),
    queryFn: async ({ pageParam, signal }): Promise<FplLeagueStandings> => {
      const read = await standings(leagueId!, pageParam, { signal });
      if (!read.ok) throw new ForwarderRefused(read.reason);
      return read.document;
    },
    initialPageParam: 1,
    getNextPageParam: (last: FplLeagueStandings) =>
      last.has_next && last.page < MAX_STANDINGS_PAGE ? last.page + 1 : undefined,
    enabled: leagueId !== null,
    ...LEAGUE_READ,
  });
}

/** The rows of the pages read so far, each entry once, in FPL's order. */
export function standingRows(pages: readonly FplLeagueStandings[] | undefined): FplStandingRow[] {
  const seen = new Set<number>();
  const rows: FplStandingRow[] = [];
  for (const page of pages ?? []) {
    for (const row of page.results) {
      if (seen.has(row.entry)) continue;
      seen.add(row.entry);
      rows.push(row);
    }
  }
  return rows;
}
