/**
 * The league context the member page's shared hooks read (`useLeagueMemberData`,
 * `useDevicePlan`, `useMemberLiveScore`), for a member read through the forwarder. Its tree
 * is built on the device from the forwarder's documents (`forwardedTree`): the table the
 * page already read, the standings pages and bundles it has, and the forwarder for the rest.
 */

import { useMemo, type ReactNode } from "react";

import type { FixturesPayload } from "../../fixtures/types";
import type { DevicePlanTableRef, PublishedLeague } from "../directory";
import type { DevicePlanDocument } from "../device/types";
import type { FplEntryBundle, FplLeagueStandings } from "../forwarder/documents";
import { LeagueContext, type LeagueContextValue } from "../LeagueContext";
import { forwardedTree, type ForwardedSources } from "./forwardedTree";
import type { LeagueViewEnvelope } from "../types";

const NONE: readonly never[] = [];

export function ForwardedTreeProvider({
  leagueId,
  leagueName,
  tableRef,
  table,
  fixtures = null,
  pages = NONE,
  bundles = NONE,
  sources,
  children,
}: {
  /** The forwarded league the page was opened from, or 0 for an entry opened on its own. */
  leagueId: number;
  leagueName: string;
  tableRef: DevicePlanTableRef;
  table: LeagueViewEnvelope<DevicePlanDocument>;
  fixtures?: FixturesPayload | null;
  /** The standings pages the page has read. */
  pages?: readonly FplLeagueStandings[];
  /** The bundles the page has read, the member's own among them. */
  bundles?: readonly FplEntryBundle[];
  /** The forwarder reads; the site's own unless a test injects them. */
  sources?: ForwardedSources;
  children: ReactNode;
}) {
  const value = useMemo<LeagueContextValue>(() => {
    const league: PublishedLeague = {
      leagueId,
      leagueName,
      season: table.payload.season,
      gameweek: table.payload.gameweek,
      path: "",
      devicePlan: tableRef,
    };
    return {
      league,
      tree: forwardedTree({ league, table, fixtures, pages, bundles, sources }),
    };
  }, [leagueId, leagueName, tableRef, table, fixtures, pages, bundles, sources]);
  return <LeagueContext.Provider value={value}>{children}</LeagueContext.Provider>;
}
