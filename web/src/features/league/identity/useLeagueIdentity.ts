/**
 * Who the visitor is on this site: the league they entered by its number, and the member
 * of that league they said they are. Every page, both gates and the sidebar read identity
 * here and nowhere else.
 *
 * A later sign-in replaces `memberClaim.ts` and the roster reconciliation in this file,
 * and `MemberPicker` becomes the sign-in step; the gates, the shell and the pages keep
 * this interface. This is a step in the flow, not access control: the published files
 * stay public.
 */
import { useCallback, useEffect, useMemo, useSyncExternalStore } from "react";

import {
  readMemberClaim,
  subscribeMemberClaim,
  writeMemberClaim,
  type MemberClaim,
} from "./memberClaim";
import { readChosenLeague, useChosenLeague, writeChosenLeague } from "./useChosenLeague";

export type { MemberClaim } from "./memberClaim";

/** The member as the visitor named them; a claim, never a verified account. */
export interface IdentifiedMember extends MemberClaim {
  verified: false;
  source: "self-selected";
}

/** A member the league publishes, by name only. */
export interface RosterEntry {
  entryId: number;
  managerName: string | null;
  teamName: string | null;
}

/** The league's human members as the member gate read them. */
export interface Roster {
  leagueName: string | null;
  entries: readonly RosterEntry[];
}

/**
 * `no-league`: no league number yet. `unclaimed`: a league, and nobody claimed in it (or a
 * claim the roster does not hold). `claimed`: a member of this league, including while
 * the roster is still being read.
 */
export type IdentityStatus = "no-league" | "unclaimed" | "claimed";

export interface LeagueIdentity {
  /** The league in the address when given, else the claim's league, else the chosen one. */
  leagueId: number | null;
  /** The member claimed in that league, or null. */
  member: IdentifiedMember | null;
  status: IdentityStatus;
  /** Enters a league; a claim made in another league is dropped, one made in it is kept. */
  chooseLeague(leagueId: number): void;
  claimMember(claim: MemberClaim): void;
  /** Drops the claim, so the next league page asks again. */
  change(): void;
}

/**
 * The identity for a page. `league` is the league the page is about (the address's), when
 * it names one. `roster`, once the member gate has read it, settles the claim: a claim whose
 * member is not in it is dropped, and changed names are written back.
 */
export function useLeagueIdentity(league?: number | null, roster?: Roster): LeagueIdentity {
  const claim = useSyncExternalStore(subscribeMemberClaim, readMemberClaim, () => null);
  const chosen = useChosenLeague().leagueId;
  const leagueId = league ?? claim?.leagueId ?? chosen;
  const member = useMemo<IdentifiedMember | null>(
    () =>
      claim !== null && claim.leagueId === leagueId
        ? { ...claim, verified: false, source: "self-selected" }
        : null,
    [claim, leagueId],
  );
  const found =
    roster === undefined || member === null
      ? undefined
      : (roster.entries.find((entry) => entry.entryId === member.entryId) ?? null);
  const rosterLeagueName = roster?.leagueName ?? null;
  const status: IdentityStatus =
    leagueId === null ? "no-league" : member === null || found === null ? "unclaimed" : "claimed";

  useEffect(() => {
    if (member === null || found === undefined) return;
    if (found === null) {
      writeMemberClaim(null);
      return;
    }
    const leagueName = rosterLeagueName ?? member.leagueName;
    if (
      found.managerName !== member.managerName ||
      found.teamName !== member.teamName ||
      leagueName !== member.leagueName
    ) {
      writeMemberClaim({
        leagueId: member.leagueId,
        entryId: member.entryId,
        managerName: found.managerName,
        teamName: found.teamName,
        leagueName,
      });
    }
  }, [member, found, rosterLeagueName]);

  const chooseLeague = useCallback((id: number) => {
    const current = readMemberClaim();
    if (current !== null && current.leagueId !== id) writeMemberClaim(null);
    if (readChosenLeague() !== id) writeChosenLeague(id);
  }, []);
  const claimMember = useCallback((next: MemberClaim) => writeMemberClaim(next), []);
  const change = useCallback(() => writeMemberClaim(null), []);

  return { leagueId, member, status, chooseLeague, claimMember, change };
}
