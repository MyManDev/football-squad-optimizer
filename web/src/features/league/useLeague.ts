/**
 * The league a page is about, read from the context the league gate provides.
 */

import { useContext } from "react";

import { LeagueContext, type LeagueContextValue } from "./LeagueContext";

/** The league in context; a page rendered outside the gate is a programming error. */
export function useLeague(): LeagueContextValue {
  const value = useContext(LeagueContext);
  if (value === null) throw new Error("useLeague needs a LeagueProvider above it.");
  return value;
}

/** The league number of the page in context. */
export function useLeagueId(): number {
  return useLeague().league.leagueId;
}
