import { useMemo, type ReactNode } from "react";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { useFixtures } from "../../fixtures/data";
import type { PublishedLeague } from "../directory";
import { LeagueEntryPage } from "../pages/LeagueEntryPage";
import { ForwardedLeagueContext, type ForwardedLeague } from "./ForwardedLeagueContext";
import { ForwardedTreeProvider } from "./ForwardedTreeProvider";
import {
  leagueRefusal,
  newestDeviceTable,
  refusalOf,
  useCaptureTable,
  useDirectory,
  useForwardedStandings,
} from "./reads";

/**
 * The league gate's way for a league the site does not publish (#983 step 4): page 1 of its
 * classic standings from the FPL forwarder. A league that answers is drawn by `children`, the
 * forwarded page the address names, with the league in context; the visitor is not asked who
 * they are here. Where the directory names a capture's table, the league's own tree stands
 * above the page too (`ForwardedTreeProvider`), so its scoreboard and race read as a listed
 * league's do; without one the page draws the standings alone. A head-to-head league, an id
 * FPL does not have and a forwarder that cannot answer each show the entry form in place,
 * saying so; the last one with the leagues the site lists.
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
  // The classic table first; a league the forwarder names as head-to-head gets its own table.
  const standings = useForwardedStandings(leagueId, 1, "auto");
  const first = standings.data;
  const name = first?.league.name ?? null;
  const scoring = first?.league.scoring ?? "classic";
  const league = useMemo<ForwardedLeague>(
    () => ({ leagueId, leagueName: name, scoring }),
    [leagueId, name, scoring],
  );
  const directory = useDirectory(first !== undefined);
  const tableRef = directory.data ? newestDeviceTable(directory.data) : null;
  const table = useCaptureTable(tableRef);
  const fixtures = useFixtures();
  const pages = useMemo(() => (first ? [first] : []), [first]);
  if (first !== undefined) {
    const page = children ?? <EmptyState title={messages.shell.notFound} />;
    const tree =
      tableRef !== null && table.data ? (
        <ForwardedTreeProvider
          leagueId={leagueId}
          leagueName={name ?? ""}
          tableRef={tableRef}
          table={table.data}
          fixtures={fixtures.data ?? null}
          pages={pages}
        >
          {page}
        </ForwardedTreeProvider>
      ) : (
        page
      );
    return <ForwardedLeagueContext.Provider value={league}>{tree}</ForwardedLeagueContext.Provider>;
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
