import { useEffect, useMemo, useRef, type ReactNode } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { useShell } from "../../../design/shell/ShellContext";
import { crossfade } from "../../../design/viewTransition";
import { useLanguage } from "../../../i18n/context";
import { asksForOwnPage, memberAddress } from "../../../lib/leagueAddresses";
import { useLeagueIdentity, type Roster, type RosterEntry } from "../identity/useLeagueIdentity";
import { useLeagueMembers } from "../queries";
import type { HumanEntryView, LeagueMembers } from "../types";
import { useLeague } from "../useLeague";
import { MemberPicker } from "./MemberPicker";

/** The league's members a visitor can be: the human rows; the system's own team never. */
function humanMembers(view: LeagueMembers): HumanEntryView[] {
  return view.members.filter((member): member is HumanEntryView => member.member_kind === "human");
}

/**
 * The second step in front of every league page: who the visitor is in this league. Until
 * they say, the page they asked for is not drawn and the picker stands in its place, at the
 * same address. Once they confirm, the page they asked for opens, or their own page when
 * they came here to find themselves (`FIND_YOURSELF`).
 *
 * The member list is the same read the league pages share, so the step costs no extra
 * request on the members, member and history pages. A claim stands while the list is
 * still being read; one the list does not hold is dropped and the picker shows.
 */
export function MemberGate({ children }: { children: ReactNode }) {
  const { league } = useLeague();
  const members = useLeagueMembers();
  const roster = useMemo<Roster | undefined>(
    () =>
      members.data
        ? {
            leagueName: league.leagueName,
            entries: humanMembers(members.data.payload).map((member) => ({
              entryId: member.entry_id,
              managerName: member.manager_name,
              teamName: member.team_name,
            })),
          }
        : undefined,
    [members.data, league.leagueName],
  );
  const { member, status, claimMember } = useLeagueIdentity(league.leagueId, roster);
  const location = useLocation();
  const navigate = useNavigate();
  const shell = useShell();
  const { messages } = useLanguage();

  // After Onayla, focus goes to the page that replaces the picker, never to a removed node.
  const focusAfterClaim = useRef(false);
  useEffect(() => {
    if (status === "claimed" && focusAfterClaim.current) {
      focusAfterClaim.current = false;
      shell?.focusPage();
    }
  }, [status, shell]);

  // The step from the picker to the page is one crossfade (#1131). The visitor's own page
  // is drawn a moment after the claim, once the redirect lands, so the new picture waits
  // for it.
  const arrived = useRef<(() => void) | null>(null);
  const ownPage = asksForOwnPage(location.state);
  useEffect(() => {
    if (status !== "claimed" || ownPage || arrived.current === null) return;
    arrived.current();
    arrived.current = null;
  }, [status, ownPage]);

  const confirm = (entry: RosterEntry) => {
    crossfade(
      () => {
        claimMember({ leagueId: league.leagueId, leagueName: league.leagueName, ...entry });
        focusAfterClaim.current = true;
        // A new key at the same address, so the shell's scroll to an id in it (#kadro) runs
        // again now that the page is drawn.
        if (!ownPage) {
          navigate(
            { pathname: location.pathname, search: location.search, hash: location.hash },
            { replace: true, state: location.state },
          );
        }
      },
      ownPage
        ? () =>
            new Promise<void>((resolve) => {
              arrived.current = resolve;
            })
        : undefined,
    );
  };

  if (status === "claimed" && member) {
    if (asksForOwnPage(location.state)) {
      return (
        <>
          <Navigate to={memberAddress(league.leagueId, member.entryId)} replace />
          <EmptyState title={messages.common.loading} />
        </>
      );
    }
    return <>{children}</>;
  }
  return (
    <MemberPicker
      key={league.leagueId}
      members={members}
      rows={roster?.entries}
      onConfirm={confirm}
    />
  );
}
