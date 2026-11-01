import { useQuery } from "@tanstack/react-query";
import { useEffect, type ReactNode } from "react";
import { Navigate, useLocation, useParams } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { leagueIdInAddress, legacyLeagueAddress } from "../../../lib/leagueAddresses";
import { LeagueDataMissing } from "../data";
import { findLeague, loadLeagueDirectory } from "../directory";
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
 * `source="visitor"` puts a page whose address names no league (the system's own pages:
 * a gameweek's squad, the moves, the rivals) behind the same two steps. The league is the
 * visitor's current one; the form asks for it in place, and once it connects the address
 * is kept and the member step follows there.
 *
 * A league address the directory does not list is read from the FPL forwarder instead
 * (#983 step 4, `ForwardedLeagueGate`): a classic league that answers draws `forwarded`, the
 * forwarded page for that address, and is never chosen as the visitor's league. A listed
 * league never asks the forwarder anything, so it opens from the published tree whether
 * the forwarder answers or not.
 */
export function LeagueGate({
  children,
  source = "address",
  forwarded,
}: {
  children: ReactNode;
  source?: "address" | "visitor";
  /** The page an unlisted classic league draws at this address; none, a not-found page. */
  forwarded?: ReactNode;
}) {
  const { messages } = useLanguage();
  const { leagueId: parameter } = useParams();
  const location = useLocation();
  // The claim's league, else the chosen one: where an address without a number goes.
  const { leagueId: current, chooseLeague } = useLeagueIdentity();
  // The number as the sidebar and the links read it: digits, or no league at all. A
  // visitor-mode page names none, so the visitor's current league stands for it.
  const named =
    source === "visitor"
      ? current
      : parameter === undefined
        ? null
        : leagueIdInAddress(location.pathname);
  const directory = useQuery({
    queryKey: leagueKeys.directory(),
    queryFn: () => loadLeagueDirectory(),
    // The form reads the directory itself when the visitor connects.
    enabled: named !== null,
    ...LEAGUE_READ,
  });

  const league = named !== null && directory.data ? findLeague(directory.data, named) : null;
  const addressLeague = source === "address" ? (league?.leagueId ?? null) : null;
  useEffect(() => {
    if (addressLeague !== null) chooseLeague(addressLeague);
  }, [addressLeague, chooseLeague]);
  if (source === "address" && parameter === undefined) {
    // The old shape of the address: the current league's version of it, or the form.
    const legacy = current === null ? null : legacyLeagueAddress(location.pathname, current);
    if (legacy !== null)
      return <Navigate to={`${legacy}${location.search}${location.hash}`} replace />;
    return <LeagueEntryPage inPlace />;
  }
  if (named === null) return <LeagueEntryPage inPlace stay={source === "visitor"} />;
  if (directory.isPending) return <EmptyState title={messages.common.loading} />;
  if (directory.isError) {
    // A directory that could not be read says so: the league may well be published.
    const missing = directory.error instanceof LeagueDataMissing;
    return (
      <EmptyState
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
  if (league === null && source === "visitor")
    return <LeagueEntryPage key={named} inPlace stay unpublishedLeagueId={named} />;
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
