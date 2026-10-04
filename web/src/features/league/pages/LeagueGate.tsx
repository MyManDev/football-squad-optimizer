import { useQuery } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { Navigate, useLocation, useParams } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { legacyLeagueAddress } from "../../../lib/leagueAddresses";
import { findLeague, loadLeagueDirectory } from "../directory";
import { useChosenLeague } from "../identity/useChosenLeague";
import { LeagueProvider } from "../LeagueProvider";
import { LEAGUE_READ, leagueKeys } from "../queries";
import { LeagueEntryPage } from "./LeagueEntryPage";

/**
 * Every league page sits behind the league number in its address. The gate reads the
 * number, finds the league in the published directory, and provides its tree to the page;
 * an address naming no league, or one the site does not publish, shows the entry form
 * where it stands. An address from before the number (`/league/members/...`) goes to the
 * same page under the league the visitor chose, or to the form when none was.
 */
export function LeagueGate({ children }: { children: ReactNode }) {
  const { messages } = useLanguage();
  const { leagueId: parameter } = useParams();
  const location = useLocation();
  const { leagueId: chosen, choose } = useChosenLeague();
  const named = parameter === undefined ? null : Number(parameter);
  const directory = useQuery({
    queryKey: leagueKeys.directory(),
    queryFn: () => loadLeagueDirectory(),
    // The form reads the directory itself when the visitor connects.
    enabled: named !== null,
    ...LEAGUE_READ,
  });

  const league = named !== null && directory.data ? findLeague(directory.data, named) : null;
  // A league reached by its address is the one the visitor is in: the form prefills it
  // and the old addresses rewrite to it from here on.
  useEffect(() => {
    if (league !== null && chosen !== league.leagueId) choose(league.leagueId);
  }, [league, chosen, choose]);
  if (named === null) {
    // The old shape of the address: the chosen league's version of it, or the form.
    const legacy = chosen === null ? null : legacyLeagueAddress(location.pathname, chosen);
    if (legacy !== null)
      return <Navigate to={`${legacy}${location.search}${location.hash}`} replace />;
    return <LeagueEntryPage inPlace />;
  }
  if (!Number.isSafeInteger(named) || named <= 0) return <LeagueEntryPage inPlace />;
  if (directory.isPending) return <EmptyState title={messages.common.loading} />;
  // A directory that could not be read says so: the league may well be published.
  if (directory.isError) return <EmptyState title={messages.leagueEntry.directoryUnreadable} />;
  if (league === null) return <LeagueEntryPage inPlace />;
  return <LeagueProvider league={league}>{children}</LeagueProvider>;
}
