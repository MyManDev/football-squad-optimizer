import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useSyncExternalStore, type ReactNode } from "react";
import { Navigate, useLocation, useParams } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { leagueIdInAddress, legacyLeagueAddress } from "../../../lib/leagueAddresses";
import { LeagueDataMissing } from "../data";
import { createLeagueTree } from "../data";
import { findLeague, loadLeagueDirectory } from "../directory";
import { readMemberClaim, subscribeMemberClaim } from "../identity/memberClaim";
import { entryIdInAddress, prefetchMemberReads } from "../prefetch";
import { ForwardedLeagueGate } from "../forwarded/ForwardedLeagueGate";
import { useLeagueIdentity } from "../identity/useLeagueIdentity";
import { LeagueProvider } from "../LeagueProvider";
import { LEAGUE_READ, leagueKeys } from "../queries";
import { LeagueEntryPage } from "./LeagueEntryPage";
import { MemberGate } from "./MemberGate";

/**
 * Every league page sits behind two steps: the league number in its address, then who
 * the visitor is in that league. The gate reads the number, finds the league in the
 * published directory and provides its tree; the member gate inside it then asks "Sen
 * kimsin?" in place until the visitor has said, and only then draws the page. An address
 * naming no league, or one the site does not publish, shows the entry form where it
 * stands. An address from before the number (`/league/members/...`) goes to the same page
 * under the visitor's current league, or to the form when there is none.
 *
 * A league reached by its address is the one the visitor is in: the gate chooses it once
 * per league it reaches. It never chooses again because the stored choice changed (another
 * tab may change it), so two tabs cannot keep choosing against each other. Every gated
 * route passes through here exactly once, so the picker never shows before the number and
 * never twice.
 *
 * A league address the directory does not list is read from the FPL forwarder instead
 * (#983 step 4, `ForwardedLeagueGate`): a classic league that answers draws `forwarded`, the
 * forwarded page for that address, and is never chosen as the visitor's league. A listed
 * league never asks the forwarder anything, so it opens from the published tree whether
 * the forwarder answers or not.
 */
export function LeagueGate({
  children,
  forwarded,
}: {
  children: ReactNode;
  /** The page an unlisted classic league draws at this address; none, a not-found page. */
  forwarded?: ReactNode;
}) {
  const { messages } = useLanguage();
  const { leagueId: parameter, entryId: entryParameter } = useParams();
  const location = useLocation();
  // The claim's league, else the chosen one: where an address without a number goes.
  const { leagueId: current, chooseLeague } = useLeagueIdentity();
  // The number as the sidebar and the links read it: digits, or no league at all.
  const named = parameter === undefined ? null : leagueIdInAddress(location.pathname);
  const directory = useQuery({
    queryKey: leagueKeys.directory(),
    queryFn: () => loadLeagueDirectory(),
    // The form reads the directory itself when the visitor connects.
    enabled: named !== null,
    ...LEAGUE_READ,
  });

  const league = named !== null && directory.data ? findLeague(directory.data, named) : null;
  const addressLeague = league?.leagueId ?? null;
  useEffect(() => {
    if (addressLeague !== null) chooseLeague(addressLeague);
  }, [addressLeague, chooseLeague]);
  // The page's own reads start here, in the same turn as its code, rather than one by one
  // once the page has mounted (prefetch.ts). Before the visitor has said who they are in
  // this league, nothing of a member is read: the picker shows names only, so the address's
  // member is started only under a claim for the league it names.
  const queryClient = useQueryClient();
  const claim = useSyncExternalStore(subscribeMemberClaim, readMemberClaim, () => null);
  const claimedHere = claim !== null && league !== null && claim.leagueId === league.leagueId;
  const entryId = claimedHere ? entryIdInAddress(entryParameter) : null;
  useEffect(() => {
    if (league !== null) prefetchMemberReads(queryClient, createLeagueTree(league), entryId);
  }, [league, entryId, queryClient]);
  if (parameter === undefined) {
    // The old shape of the address: the current league's version of it, or the form.
    const legacy = current === null ? null : legacyLeagueAddress(location.pathname, current);
    if (legacy !== null)
      return <Navigate to={`${legacy}${location.search}${location.hash}`} replace />;
    return <LeagueEntryPage inPlace />;
  }
  if (named === null) return <LeagueEntryPage inPlace />;
  if (directory.isPending) return <EmptyState title={messages.common.loading} />;
  if (directory.isError) {
    // A directory that could not be read says so: the league may well be published.
    const missing = directory.error instanceof LeagueDataMissing;
    return (
      <EmptyState
        page
        title={
          missing ? messages.leagueEntry.directoryMissing : messages.leagueEntry.directoryUnreadable
        }
      >
        <button type="button" onClick={() => void directory.refetch()}>
          {messages.leagueEntry.retry}
        </button>
      </EmptyState>
    );
  }
  if (league === null)
    return (
      <ForwardedLeagueGate key={named} leagueId={named} listed={directory.data.leagues}>
        {forwarded}
      </ForwardedLeagueGate>
    );
  return (
    <LeagueProvider league={league}>
      <MemberGate>{children}</MemberGate>
    </LeagueProvider>
  );
}
