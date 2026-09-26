import { useQuery } from "@tanstack/react-query";

import { loadEntrySquad, loadLeagueMembers, loadScoreboard } from "./data";

/**
 * How every league read behaves, written once. A published league file is there or it is
 * not: a missing one is a normal state the page says at once, and an unreadable one shows
 * its own "read again" control, so no read is repeated behind the reader's back. A document
 * read in the last minute is served from the cache.
 */
export const LEAGUE_READ = { retry: false, staleTime: 60_000 } as const;

/** The cache keys more than one league page reads: one spelling each, so the pages share one read. */
export const leagueKeys = {
  members: () => ["provisional-league-members"] as const,
  scoreboard: () => ["provisional-league-scoreboard"] as const,
  entrySquad: (entryId: number | null | undefined) =>
    ["provisional-entry-squad", entryId ?? null] as const,
};

export function useLeagueMembers(enabled = true) {
  return useQuery({
    queryKey: leagueKeys.members(),
    queryFn: loadLeagueMembers,
    enabled,
    ...LEAGUE_READ,
  });
}

export function useLeagueScoreboard() {
  return useQuery({ queryKey: leagueKeys.scoreboard(), queryFn: loadScoreboard, ...LEAGUE_READ });
}

/** One entry's squad document; nothing is read while there is no entry to read. */
export function useEntrySquad(entryId: number | null | undefined, enabled = true) {
  return useQuery({
    queryKey: leagueKeys.entrySquad(entryId),
    queryFn: () => loadEntrySquad(entryId!),
    enabled: enabled && entryId != null,
    ...LEAGUE_READ,
  });
}
