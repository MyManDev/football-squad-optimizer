/**
 * The forwarded pages' reads (#983 step 4): a classic league's standings, page by page from
 * the FPL forwarder, the capture's own table the directory names newest, and one entry's
 * bundle for that table's gameweek. Each spreads the league feature's read policy.
 */

import { useQuery } from "@tanstack/react-query";

import { loadDevicePlanTable } from "../data";
import { loadLeagueDirectory, type DevicePlanTableRef, type LeagueDirectory } from "../directory";
import {
  entryBundle,
  h2hMatches,
  h2hStandings,
  standings,
  type ForwarderReason,
  type StandingsReason,
} from "../forwarder/client";
import {
  MAX_STANDINGS_PAGE,
  type ForwardedTable,
  type FplH2hMatches,
} from "../forwarder/documents";
import type { ForwardedScoring } from "./ForwardedLeagueContext";
import { LEAGUE_READ, leagueKeys } from "../queries";

/** The forwarded reads' cache keys, each naming its league, entry or table. */
export const forwardedKeys = {
  // One key whatever the scoring asked: a league keeps one table, and the gate's "auto" read
  // and the page's read of the same page are the same document.
  standings: (leagueId: number, page = 1) => ["fpl-standings", leagueId, page] as const,
  matches: (leagueId: number, gameweek: number, page = 1) =>
    ["fpl-h2h-matches", leagueId, gameweek, page] as const,
  table: (table: DevicePlanTableRef | null) =>
    ["device-capture-table", table?.path ?? null, table?.sha256 ?? null] as const,
  bundle: (entryId: number, gameweek: number | null) =>
    ["fpl-entry-bundle", entryId, gameweek] as const,
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
 * One requested page of a league's table. The gate and table share page 1; browsing never
 * downloads the intervening pages or every member of a large league. `leagueId` null reads
 * nothing. `scoring` names which table: the gate asks for "auto", the classic table first
 * and, where the forwarder names a head-to-head league, that league's own table.
 */
export function useForwardedStandings(
  leagueId: number | null,
  page = 1,
  scoring: ForwardedScoring | "auto" = "classic",
) {
  return useQuery({
    queryKey: forwardedKeys.standings(leagueId ?? 0, page),
    queryFn: async ({ signal }): Promise<ForwardedTable> => {
      if (scoring !== "h2h") {
        const classic = await standings(leagueId!, page, { signal });
        if (classic.ok) return classic.document;
        if (scoring === "classic" || classic.reason !== "head_to_head_league") {
          throw new ForwarderRefused(classic.reason);
        }
      }
      const cup = await h2hStandings(leagueId!, page, { signal });
      // A head-to-head league whose own table the forwarder cannot serve yet is still named
      // as head-to-head, so the entry form says what it always said of one.
      if (!cup.ok)
        throw new ForwarderRefused(scoring === "auto" ? "head_to_head_league" : cup.reason);
      return cup.document;
    },
    enabled: leagueId !== null,
    ...LEAGUE_READ,
  });
}

/** One page of a head-to-head league's pairings for one gameweek; nothing for a null league. */
export function useForwardedMatches(leagueId: number | null, gameweek: number | null, page = 1) {
  return useQuery({
    queryKey: forwardedKeys.matches(leagueId ?? 0, gameweek ?? 0, page),
    queryFn: async ({ signal }): Promise<FplH2hMatches> => {
      const read = await h2hMatches(leagueId!, gameweek!, page, { signal });
      if (!read.ok) throw new ForwarderRefused(read.reason);
      return read.document;
    },
    enabled: leagueId !== null && gameweek !== null,
    ...LEAGUE_READ,
  });
}

/** A URL/history page is bounded before it can become a forwarder request. */
export function standingsPage(value: unknown): number {
  if (typeof value !== "string" && typeof value !== "number") return 1;
  const page = Number(value);
  return /^\d+$/.test(String(value)) &&
    Number.isSafeInteger(page) &&
    page >= 1 &&
    page <= MAX_STANDINGS_PAGE
    ? page
    : 1;
}

/**
 * The capture's own table the directory names newest: the line of the latest season and
 * gameweek, the later capture on a tie (a capture id carries its UTC time). Null where no
 * line names one.
 */
export function newestDeviceTable(directory: LeagueDirectory): DevicePlanTableRef | null {
  const capture = (table: DevicePlanTableRef) => table.path.split("/")[1] ?? "";
  let newest: { season: string; gameweek: number; table: DevicePlanTableRef } | null = null;
  for (const { season, gameweek, devicePlan: table } of directory.leagues) {
    if (table === undefined) continue;
    const later =
      newest === null ||
      season > newest.season ||
      (season === newest.season &&
        (gameweek > newest.gameweek ||
          (gameweek === newest.gameweek && capture(table) > capture(newest.table))));
    if (later) newest = { season, gameweek, table };
  }
  return newest?.table ?? null;
}

/** The published directory, under the key the league gate reads it by. */
export function useDirectory(enabled = true) {
  return useQuery({
    queryKey: leagueKeys.directory(),
    queryFn: () => loadLeagueDirectory(),
    enabled,
    ...LEAGUE_READ,
  });
}

/** The capture's own table a directory line names: null where it cannot be read as one. */
export function useCaptureTable(table: DevicePlanTableRef | null) {
  return useQuery({
    queryKey: forwardedKeys.table(table),
    queryFn: ({ signal }) => loadDevicePlanTable(table!, { signal }),
    enabled: table !== null,
    ...LEAGUE_READ,
  });
}

/** One entry's bundle for the table's gameweek, as the forwarder answers it. */
export function useEntryBundle(entryId: number, gameweek: number | null) {
  return useQuery({
    queryKey: forwardedKeys.bundle(entryId, gameweek),
    queryFn: async ({ signal }) => {
      const read = await entryBundle(entryId, gameweek!, { signal });
      // A read the page stopped is no answer to keep.
      if (!read.ok && read.reason === "aborted") throw new ForwarderRefused(read.reason);
      return read;
    },
    enabled: gameweek !== null && Number.isSafeInteger(entryId) && entryId > 0,
    ...LEAGUE_READ,
  });
}
