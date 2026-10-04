/**
 * The sidebar's navigation, worked out from the address alone.
 *
 * 'Bu hafta' is the member's decision page when a member is in context, with the plan the
 * address carries, and the league entry page when none is. 'Kadro' is the same page at its
 * squad and exists only with a member. 'Lig' is the member list of the league in the
 * address, or of the league the visitor chose, never the system's league analysis.
 * Nothing here reads or writes browser storage; the chosen league is handed in.
 */
import { leagueIdInAddress, memberAddress, membersAddress } from "../../lib/leagueAddresses";

export type NavKey = "thisWeek" | "squad" | "league" | "fixtures" | "contribute";

export interface NavItem {
  key: NavKey;
  to: string;
  active: boolean;
}

export interface MemberContext {
  leagueId: number;
  entryId: string;
  /** The decision page's query string with its leading '?', or "" for none. */
  search: string;
}

export interface Place {
  pathname: string;
  search: string;
  hash: string;
}

export const SQUAD_HASH = "#kadro";

const MEMBER_PAGE = /^\/league\/(\d+)\/members\/(\d+)$/;
const MEMBER_HISTORY = /^\/league\/(\d+)\/members\/(\d+)\/history$/;

function path(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

/**
 * The member an address is about. Only a published member's number counts: the system's
 * paper squad at /league/members/squadopt is not a member and is never linked from here.
 */
export function memberAt(
  place: Place,
): { leagueId: number; entryId: string; search: string | null } | null {
  const pathname = path(place.pathname);
  const page = MEMBER_PAGE.exec(pathname);
  if (page) return { leagueId: Number(page[1]), entryId: page[2]!, search: place.search };
  const history = MEMBER_HISTORY.exec(pathname);
  if (history) return { leagueId: Number(history[1]), entryId: history[2]!, search: null };
  return null;
}

/**
 * Which member 'Bu hafta' opens: the one the address names, else the member the visitor
 * said they are (held in memory only), else the member page last opened in this visit.
 * A page with no plan of its own (the history) returns to the plan last seen for that
 * member, or to the member's default plan.
 */
export function memberInContext(
  place: Place,
  viewerEntryId: number | null,
  lastSeen: MemberContext | null,
  chosenLeagueId: number | null = null,
): MemberContext | null {
  const planFor = (entryId: string) => (lastSeen?.entryId === entryId ? lastSeen.search : "");
  const here = memberAt(place);
  if (here) {
    return {
      leagueId: here.leagueId,
      entryId: here.entryId,
      search: here.search ?? planFor(here.entryId),
    };
  }
  // The member the visitor said they are belongs to the league they chose; without a
  // league there is no address for them.
  if (viewerEntryId !== null && chosenLeagueId !== null) {
    const entryId = String(viewerEntryId);
    return { leagueId: chosenLeagueId, entryId, search: planFor(entryId) };
  }
  return lastSeen;
}

export function navItems(
  place: Place,
  member: MemberContext | null,
  chosenLeagueId: number | null = null,
): NavItem[] {
  const pathname = path(place.pathname);
  const onMemberPage = member !== null && MEMBER_PAGE.exec(pathname)?.[2] === member.entryId;
  const onSquad = onMemberPage && place.hash === SQUAD_HASH;
  const memberPath = member ? memberAddress(member.leagueId, member.entryId, member.search) : null;
  const leagueId = leagueIdInAddress(pathname) ?? member?.leagueId ?? chosenLeagueId;
  const leaguePath = leagueId === null ? "/" : membersAddress(leagueId);

  const items: NavItem[] = [
    {
      key: "thisWeek",
      to: memberPath ?? "/",
      active: memberPath ? onMemberPage && !onSquad : pathname === "/",
    },
  ];
  if (memberPath) items.push({ key: "squad", to: `${memberPath}${SQUAD_HASH}`, active: onSquad });
  items.push(
    { key: "league", to: leaguePath, active: leagueId !== null && pathname === leaguePath },
    { key: "fixtures", to: "/fixtures", active: pathname === "/fixtures" },
    { key: "contribute", to: "/contribute", active: pathname === "/contribute" },
  );
  return items;
}
