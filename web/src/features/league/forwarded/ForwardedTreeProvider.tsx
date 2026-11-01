/**
 * The league context the member page's shared hooks read (`useDevicePlan`,
 * `useMemberLiveScore`), for a member read through the forwarder. They ask the context's tree
 * for the capture's table; here it answers with the table the page already read, and every
 * other document as not published, since nothing is published for a forwarded league or entry.
 */

import { useMemo, type ReactNode } from "react";

import type { DevicePlanTableRef, PublishedLeague } from "../directory";
import type { DevicePlanDocument } from "../device/types";
import { LeagueContext, type LeagueContextValue } from "../LeagueContext";
import { forwardedTree } from "./forwardedTree";
import type { LeagueViewEnvelope } from "../types";

export function ForwardedTreeProvider({
  leagueId,
  leagueName,
  tableRef,
  table,
  children,
}: {
  /** The forwarded league the page was opened from, or 0 for an entry opened on its own. */
  leagueId: number;
  leagueName: string;
  tableRef: DevicePlanTableRef;
  table: LeagueViewEnvelope<DevicePlanDocument>;
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
    return { league, tree: forwardedTree(league, table) };
  }, [leagueId, leagueName, tableRef, table]);
  return <LeagueContext.Provider value={value}>{children}</LeagueContext.Provider>;
}
