import type { ReactNode } from "react";

import { SUPPORTED_LEAGUE_ID } from "../data";
import { useChosenLeague } from "../identity/useChosenLeague";
import { LeagueEntryPage } from "./LeagueEntryPage";

/**
 * Every league page sits behind the league number. A visitor who arrives by a direct
 * link sees the entry form at that address and, once the number is in, the page itself.
 */
export function LeagueGate({ children }: { children: ReactNode }) {
  const { leagueId } = useChosenLeague();
  if (leagueId !== SUPPORTED_LEAGUE_ID) return <LeagueEntryPage inPlace />;
  return children;
}
