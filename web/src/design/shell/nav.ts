/**
 * The sidebar's navigation, worked out from the address alone.
 *
 * 'Bu hafta' is the member's decision page when a member is in context, with the plan the
 * address carries, and the league entry page when none is. 'Kadro' is the same page at its
 * squad and exists only with a member. 'Lig' is the member list, never the system's league
 * analysis at /league. Nothing here reads or writes browser storage.
 */
export type NavKey = "thisWeek" | "squad" | "league" | "fixtures" | "contribute";

export interface NavItem {
  key: NavKey;
  to: string;
  active: boolean;
}

export interface MemberContext {
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

const MEMBER_PAGE = /^\/league\/members\/(\d+)$/;
const MEMBER_HISTORY = /^\/league\/members\/(\d+)\/history$/;

function path(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

/**
 * The member an address is about. Only a published member's number counts: the system's
 * paper squad at /league/members/squadopt is not a member and is never linked from here.
 */
export function memberAt(place: Place): { entryId: string; search: string | null } | null {
  const pathname = path(place.pathname);
  const page = MEMBER_PAGE.exec(pathname);
  if (page) return { entryId: page[1]!, search: place.search };
  const history = MEMBER_HISTORY.exec(pathname);
  if (history) return { entryId: history[1]!, search: null };
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
): MemberContext | null {
  const planFor = (entryId: string) => (lastSeen?.entryId === entryId ? lastSeen.search : "");
  const here = memberAt(place);
  if (here) return { entryId: here.entryId, search: here.search ?? planFor(here.entryId) };
  if (viewerEntryId !== null) {
    const entryId = String(viewerEntryId);
    return { entryId, search: planFor(entryId) };
  }
  return lastSeen;
}

export function navItems(place: Place, member: MemberContext | null): NavItem[] {
  const pathname = path(place.pathname);
  const onMemberPage = member !== null && MEMBER_PAGE.exec(pathname)?.[1] === member.entryId;
  const onSquad = onMemberPage && place.hash === SQUAD_HASH;
  const memberPath = member ? `/league/members/${member.entryId}${member.search}` : null;

  const items: NavItem[] = [
    {
      key: "thisWeek",
      to: memberPath ?? "/",
      active: memberPath ? onMemberPage && !onSquad : pathname === "/",
    },
  ];
  if (memberPath) items.push({ key: "squad", to: `${memberPath}${SQUAD_HASH}`, active: onSquad });
  items.push(
    { key: "league", to: "/league/members", active: pathname === "/league/members" },
    { key: "fixtures", to: "/fixtures", active: pathname === "/fixtures" },
    { key: "contribute", to: "/contribute", active: pathname === "/contribute" },
  );
  return items;
}
