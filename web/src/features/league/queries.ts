import { useQuery } from "@tanstack/react-query";

import { useLeague } from "./useLeague";

/**
 * How the league feature's own reads behave, written once. Every `useQuery` call inside
 * features/league spreads one of these policies: the provisional league tree's documents
 * use LEAGUE_READ; the compute service's capabilities use CAPABILITIES_READ.
 *
 * A published league file is there or it is not. A missing one is a normal state the page
 * says at once. A failed read is not retried: the page offers a read-again control, shows a
 * notice, or goes on without it, and the read runs again when a page that holds it is next
 * opened, or on reload. A read that succeeded in the last minute is served from the cache.
 * Capabilities also refresh on focus once stale, to expose changed decision information.
 * This is a read, never a compute request, and introduces no polling interval.
 *
 * Outside this rule: /league (pages/LeaguePage.tsx) reads the site index, the ledger and the
 * season's league.json through data/queries.ts, which the score pages share, so those reads
 * keep the client default of one retry. queries.test.tsx counts the useQuery calls written
 * out in each module, so it cannot see a read made through a hook imported from elsewhere. It
 * does find the league modules that import data/queries.ts, and fails when one of them is not
 * named here.
 */
export const LEAGUE_READ = { retry: false, staleTime: 60_000 } as const;

export const CAPABILITIES_READ = {
  retry: LEAGUE_READ.retry,
  staleTime: LEAGUE_READ.staleTime,
  refetchOnWindowFocus: true,
} as const;

/**
 * The cache keys more than one league page reads: one spelling each, so the pages share one
 * read; every key names the league, so two leagues' documents never share a cache entry.
 */
export const leagueKeys = {
  directory: () => ["league-directory"] as const,
  members: (leagueId: number) => ["provisional-league-members", leagueId] as const,
  scoreboard: (leagueId: number) => ["provisional-league-scoreboard", leagueId] as const,
  entrySquad: (leagueId: number, entryId: number | null | undefined) =>
    ["provisional-entry-squad", leagueId, entryId ?? null] as const,
  adviceIndex: (leagueId: number, entryId: number) =>
    ["provisional-entry-advice-index", leagueId, entryId] as const,
};

export function useLeagueMembers(enabled = true) {
  const { league, tree } = useLeague();
  return useQuery({
    queryKey: leagueKeys.members(league.leagueId),
    queryFn: () => tree.members(),
    enabled,
    ...LEAGUE_READ,
  });
}

export function useLeagueScoreboard() {
  const { league, tree } = useLeague();
  return useQuery({
    queryKey: leagueKeys.scoreboard(league.leagueId),
    queryFn: () => tree.scoreboard(),
    ...LEAGUE_READ,
  });
}

/** One entry's squad document; nothing is read while there is no entry to read. */
export function useEntrySquad(entryId: number | null | undefined, enabled = true) {
  const { league, tree } = useLeague();
  return useQuery({
    queryKey: leagueKeys.entrySquad(league.leagueId, entryId),
    queryFn: () => tree.entrySquad(entryId!),
    enabled: enabled && entryId != null,
    ...LEAGUE_READ,
  });
}
