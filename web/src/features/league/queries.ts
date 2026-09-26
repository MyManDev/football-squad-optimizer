import { useQuery } from "@tanstack/react-query";

import { loadEntrySquad, loadLeagueMembers, loadScoreboard } from "./data";

/**
 * How the league feature's own reads behave, written once. Every `useQuery` call inside
 * features/league spreads it: the provisional league tree's documents (members, scoreboard,
 * squads, advice index, advice, window control, suggestion history, live series) and the
 * compute service's capabilities.
 *
 * A published league file is there or it is not. A missing one is a normal state the page
 * says at once. A failed read is not retried: the page offers a read-again control, shows a
 * notice, or goes on without it, and the read runs again when a page that holds it is next
 * opened, or on reload. A read that succeeded in the last minute is served from the cache.
 *
 * Outside this rule: /league (pages/LeaguePage.tsx) reads the site index, the ledger and the
 * season's league.json through data/queries.ts, which the score pages share, so those reads
 * keep the client default of one retry. queries.test.tsx counts the useQuery calls written
 * out in each module, so it cannot see a read made through a hook imported from elsewhere. It
 * does find the league modules that import data/queries.ts, and fails when one of them is not
 * named here.
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
