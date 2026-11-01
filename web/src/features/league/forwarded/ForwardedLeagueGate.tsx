import { useMemo, type ReactNode } from "react";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import type { PublishedLeague } from "../directory";
import { LeagueEntryPage } from "../pages/LeagueEntryPage";
import { ForwardedLeagueContext, type ForwardedLeague } from "./ForwardedLeagueContext";
import { leagueRefusal, refusalOf, useForwardedStandings } from "./reads";

/**
 * The league gate's way for a league the site does not publish (#983 step 4): page 1 of its
 * classic standings from the FPL forwarder. A league that answers is drawn by `children`, the
 * forwarded page the address names, with the league in context; nothing published is read
 * for it, and the visitor is not asked who they are. A head-to-head league, an id FPL does
 * not have and a forwarder that cannot answer each show the entry form in place, saying so;
 * the last one with the leagues the site lists.
 */
export function ForwardedLeagueGate({
  leagueId,
  listed,
  children,
}: {
  leagueId: number;
  listed: readonly PublishedLeague[];
  children?: ReactNode;
}) {
  const { messages } = useLanguage();
  const standings = useForwardedStandings(leagueId);
  const first = standings.data?.pages[0];
  const name = first?.league.name ?? null;
  const league = useMemo<ForwardedLeague>(() => ({ leagueId, leagueName: name }), [leagueId, name]);
  if (first !== undefined) {
    return (
      <ForwardedLeagueContext.Provider value={league}>
        {children ?? <EmptyState title={messages.shell.notFound} />}
      </ForwardedLeagueContext.Provider>
    );
  }
  if (standings.isPending || standings.isFetching) {
    return <EmptyState title={messages.forwarded.loading} />;
  }
  return (
    <LeagueEntryPage
      inPlace
      unopened={{ leagueId, refusal: leagueRefusal(refusalOf(standings.error)) }}
      listed={listed}
      onRetry={() => void standings.refetch()}
    />
  );
}
