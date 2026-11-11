import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Navigate, useLocation, useNavigate } from "react-router";

import { recordUsage } from "../../../data/usage";
import { EmptyState } from "../../../design/components/EmptyState";
import { useShell } from "../../../design/shell/ShellContext";
import { crossfade } from "../../../design/viewTransition";
import { useLanguage } from "../../../i18n/context";
import { asksForOwnPage, memberAddress } from "../../../lib/leagueAddresses";
import { useForwardedLeague, type ForwardedScoring } from "../forwarded/ForwardedLeagueContext";
import { tableRows } from "../forwarder/documents";
import { useForwardedStandings, useForwardedStandingsPages } from "../forwarded/reads";
import {
  useClaimedEntry,
  useLeagueIdentity,
  type Roster,
  type RosterEntry,
} from "../identity/useLeagueIdentity";
import { useLeagueMembers } from "../queries";
import type { HumanEntryView, LeagueMembers } from "../types";
import { prefetchMemberReads } from "../prefetch";
import { useLeague } from "../useLeague";
import { MemberPicker } from "./MemberPicker";

/** The league's members a visitor can be: the human rows; the system's own team never. */
function humanMembers(view: LeagueMembers): HumanEntryView[] {
  return view.members.filter((member): member is HumanEntryView => member.member_kind === "human");
}

/** The most pages of a forwarded league the member step reads looking for one name. */
const MOST_PAGES = 40;

/**
 * The further standings pages of a forwarded league, read one at a time as the member step
 * asks for them: the rows they add to the roster, whether the last page read says the league
 * goes on, whether a page is being read now, and the ask itself. A listed league reads none.
 */
function useFurtherMembers(leagueId: number | null, scoring: ForwardedScoring) {
  const first = useForwardedStandings(leagueId, 1, scoring);
  const [wanted, setWanted] = useState(0);
  const pages = useMemo(() => Array.from({ length: wanted }, (_, index) => index + 2), [wanted]);
  const further = useForwardedStandingsPages(leagueId, pages, scoring);
  const rows = useMemo<RosterEntry[]>(
    () =>
      further.flatMap((read) =>
        read.data
          ? tableRows(read.data).map((row) => ({
              entryId: row.entry,
              managerName: row.player_name,
              teamName: row.entry_name,
            }))
          : [],
      ),
    [further],
  );
  const last = further.at(-1)?.data ?? first.data;
  const reading = further.some((read) => read.isPending);
  const more =
    leagueId !== null && !reading && (last?.has_next ?? false) && wanted < MOST_PAGES - 1;
  const ask = useCallback(() => setWanted((count) => Math.min(count + 1, MOST_PAGES - 1)), []);
  return { rows, more, reading, ask };
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
  const { league, tree } = useLeague();
  // A row the finger lands on has its member's documents started before the tap confirms
  // it (prefetch.ts), so the page it opens finds them in the cache or on their way.
  const queryClient = useQueryClient();
  // In front of LIVE, LIVE's fewer reads: no scoreboard or history it never opens.
  const page = useLocation().pathname.endsWith("/live") ? "live" : "member";
  const warm = useCallback(
    (entry: RosterEntry) => prefetchMemberReads(queryClient, tree, entry.entryId, [], page),
    [queryClient, tree, page],
  );
  const members = useLeagueMembers();
  // A forwarded league's roster is page 1 of its table; the pages after it are read as a
  // name or a claim asks for them, never all at once.
  const forwarded = useForwardedLeague();
  const further = useFurtherMembers(
    forwarded === null ? null : forwarded.leagueId,
    forwarded?.scoring ?? "classic",
  );
  const { rows: furtherRows, more, reading, ask } = further;
  const entries = useMemo<RosterEntry[] | undefined>(() => {
    if (!members.data) return undefined;
    const own = humanMembers(members.data.payload).map((member) => ({
      entryId: member.entry_id,
      managerName: member.manager_name,
      teamName: member.team_name,
    }));
    const known = new Set(own.map((entry) => entry.entryId));
    return own.concat(furtherRows.filter((row) => !known.has(row.entryId)));
  }, [members.data, furtherRows]);
  // A claim made on a later page is looked for there before the roster can drop it: the
  // roster stays unread until the claimed member is found or the pages run out.
  const claimedHere = useClaimedEntry(league.leagueId);
  const seekingClaim =
    claimedHere !== null &&
    entries !== undefined &&
    !entries.some((entry) => entry.entryId === claimedHere) &&
    (more || reading);
  useEffect(() => {
    if (seekingClaim && more) ask();
  }, [seekingClaim, more, ask]);
  const roster = useMemo<Roster | undefined>(
    () =>
      entries !== undefined && !seekingClaim
        ? { leagueName: league.leagueName, entries }
        : undefined,
    [entries, seekingClaim, league.leagueName],
  );
  const { member, status, claimMember } = useLeagueIdentity(league.leagueId, roster);
  const location = useLocation();
  const navigate = useNavigate();
  const shell = useShell();
  const { messages } = useLanguage();

  // After a name is chosen, focus goes to the page that replaces the picker, never to a removed node.
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

  // One step per choice: a second choice before the first transition's update has run
  // (two Enter presses in one frame) is ignored, so it neither starts a transition that
  // skips the first nor writes the claim and the history entry again. The update clears
  // it, and where there is no transition the update has already run when `crossfade`
  // returns.
  const stepping = useRef(false);
  const confirm = (entry: RosterEntry) => {
    if (stepping.current) return;
    stepping.current = true;
    crossfade(
      () => {
        stepping.current = false;
        recordUsage({ step: "picker_claimed" });
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

  const picking = !(status === "claimed" && member);
  useEffect(() => {
    if (picking) recordUsage({ step: "picker_shown" });
  }, [picking, league.leagueId]);

  if (!picking) {
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
      more={more}
      reading={reading}
      onMore={ask}
      onConfirm={confirm}
      onWarm={warm}
    />
  );
}
