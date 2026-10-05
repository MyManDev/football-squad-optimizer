/**
 * Provides the league a page is about, and the tree it reads, to everything under it.
 * The league gate renders this from the address and the directory.
 */

import { useMemo, type ReactNode } from "react";

import { createLeagueTree } from "./data";
import type { PublishedLeague } from "./directory";
import { LeagueContext, type LeagueContextValue } from "./LeagueContext";

export function LeagueProvider({
  league,
  children,
}: {
  league: PublishedLeague;
  children: ReactNode;
}) {
  const value = useMemo<LeagueContextValue>(
    () => ({ league, tree: createLeagueTree(league) }),
    [league],
  );
  return <LeagueContext.Provider value={value}>{children}</LeagueContext.Provider>;
}
