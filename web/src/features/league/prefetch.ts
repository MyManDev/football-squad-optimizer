/**
 * The member page's first reads, started as soon as the league gate knows the league.
 *
 * Measured on the live site at phone width, the page's documents were read in five turns:
 * the directory, then the page's code, then the squad, the member list, the fixtures and the
 * advice index, and only then the compute service's capabilities. Each turn is a round trip a
 * phone pays in full. The gate knows the league and the member from the address once the
 * directory is read, so these reads start there, under the same keys and policies the page
 * reads them by (`queries.ts`, `fixtures/data.ts`); the page then finds them in the cache or
 * joins the read in flight. Nothing is read twice, and a league address without a member
 * starts the member list alone, which the member gate reads anyway.
 */

import type { QueryClient } from "@tanstack/react-query";

import { prefetchFixtures } from "../fixtures/data";
import type { LeagueTree } from "./data";
import { LEAGUE_READ, leagueKeys } from "./queries";

export function prefetchMemberReads(
  client: QueryClient,
  tree: LeagueTree,
  entryId: number | null,
): void {
  const leagueId = tree.league.leagueId;
  void client.prefetchQuery({
    queryKey: leagueKeys.members(leagueId),
    queryFn: () => tree.members(),
    ...LEAGUE_READ,
  });
  if (entryId === null) return;
  void client.prefetchQuery({
    queryKey: leagueKeys.entrySquad(leagueId, entryId),
    queryFn: () => tree.entrySquad(entryId),
    ...LEAGUE_READ,
  });
  void client.prefetchQuery({
    queryKey: leagueKeys.adviceIndex(leagueId, entryId),
    queryFn: () => tree.entryAdviceIndex(entryId),
    ...LEAGUE_READ,
  });
  prefetchFixtures(client);
}

/** The member named by a member page's address, or null on any other league address. */
export function entryIdInAddress(entryParameter: string | undefined): number | null {
  if (entryParameter === undefined) return null;
  const entryId = Number(entryParameter);
  return Number.isSafeInteger(entryId) && entryId > 0 ? entryId : null;
}
