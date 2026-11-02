/**
 * The sidebar's navigation, worked out from the address and the visitor's identity.
 *
 * The league part of the sidebar opens only after both steps, for the same league: a
 * league number, then the member the visitor said they are in it. Until then the first
 * item is 'Ligini bul': the league-number form with no league, or the "Sen kimsin?" step
 * of the league entered; 'Bu hafta' and 'Lig' are not there at all. Once both steps are
 * taken, 'Bu hafta' always means the claimed member's own page (on a rival's page too),
 * 'Lig' is the league's member list, and each of the member's tools (the squad held now,
 * the what-if squad, the duel, the chips and the squad card) is a page of its own under
 * their page, and so is their weekly suggestion history. The rule holds per league, so
 * it stands unchanged with many leagues published.
 *
 * Nothing here reads or writes browser storage; the identity is handed in.
 */
import {
  FIND_YOURSELF,
  isMemberTool,
  leagueIdInAddress,
  memberAddress,
  memberHistoryAddress,
  membersAddress,
  memberToolAddress,
  MEMBER_TOOLS,
  type IdentityStep,
  type MemberTool,
} from "../../lib/leagueAddresses";

/** The sidebar item of each of the member's tool pages, in the sidebar's order. */
export const TOOL_NAV = {
  "current-squad": "currentSquad",
  "what-if": "whatIf",
  duel: "duel",
  chips: "chips",
  card: "squadCard",
} as const satisfies Record<MemberTool, string>;

type ToolNavKey = (typeof TOOL_NAV)[MemberTool];

export type NavKey =
  "findLeague" | "thisWeek" | "league" | ToolNavKey | "history" | "fixtures" | "contribute";

export interface NavItem {
  key: NavKey;
  to: string;
  /** What the link asks of the identity step, carried in the router's state. */
  state?: IdentityStep;
  active: boolean;
}

/** A member page the visitor opened, with the plan its address carried. */
export interface MemberContext {
  leagueId: number;
  entryId: string;
  /** The decision page's query string with its leading '?', or "" for none. */
  search: string;
}

/** The claimed member as the sidebar shows them. */
export interface ShellMember {
  entryId: number;
  /** The league's name, or its number in words when the name is not known. */
  league: string;
  name: string;
  /** The team, shown under the manager's name; null when the name already is the team. */
  team: string | null;
}

/** The league the visitor is in and the member they said they are in it, if any. */
export interface ShellIdentity {
  leagueId: number | null;
  member: ShellMember | null;
}

export const NO_IDENTITY: ShellIdentity = { leagueId: null, member: null };

export interface Place {
  pathname: string;
  search: string;
  hash: string;
}

const MEMBER_PAGE = /^\/league\/(\d+)\/members\/(\d+)$/;
const MEMBER_HISTORY = /^\/league\/(\d+)\/members\/(\d+)\/history$/;
const MEMBER_TOOL = /^\/league\/(\d+)\/members\/(\d+)\/([a-z-]+)$/;

function path(pathname: string): string {
  return pathname.length > 1 ? pathname.replace(/\/+$/, "") : pathname;
}

/** The member an address is about. Only a published member's number counts. */
export function memberAt(
  place: Place,
): { leagueId: number; entryId: string; search: string | null } | null {
  const pathname = path(place.pathname);
  const page = MEMBER_PAGE.exec(pathname);
  if (page) return { leagueId: Number(page[1]), entryId: page[2]!, search: place.search };
  const history = MEMBER_HISTORY.exec(pathname);
  if (history) return { leagueId: Number(history[1]), entryId: history[2]!, search: null };
  // A tool page carries the plan in its address as the decision page does.
  const tool = MEMBER_TOOL.exec(pathname);
  if (tool && isMemberTool(tool[3])) {
    return { leagueId: Number(tool[1]), entryId: tool[2]!, search: place.search };
  }
  return null;
}

/**
 * The sidebar's items. `lastSeen` is the claimed member's own page as last opened in this
 * visit: 'Bu hafta' and the tool pages keep its plan, only for that member in that league.
 */
export function navItems(
  place: Place,
  identity: ShellIdentity,
  lastSeen: MemberContext | null = null,
): NavItem[] {
  const pathname = path(place.pathname);
  const { leagueId, member } = identity;
  const items: NavItem[] = [];

  if (leagueId === null) {
    items.push({ key: "findLeague", to: "/", active: pathname === "/" });
  } else if (member === null) {
    items.push({
      key: "findLeague",
      to: membersAddress(leagueId),
      state: FIND_YOURSELF,
      active: leagueIdInAddress(pathname) === leagueId,
    });
  } else {
    const entryId = String(member.entryId);
    const plan =
      lastSeen !== null && lastSeen.leagueId === leagueId && lastSeen.entryId === entryId
        ? lastSeen.search
        : "";
    const own = memberAddress(leagueId, entryId);
    const league = membersAddress(leagueId);
    const history = memberHistoryAddress(leagueId, entryId);
    items.push(
      { key: "thisWeek", to: `${own}${plan}`, active: pathname === own },
      { key: "league", to: league, active: pathname === league },
      ...MEMBER_TOOLS.map((tool) => {
        const page = memberToolAddress(leagueId, entryId, tool);
        return { key: TOOL_NAV[tool], to: `${page}${plan}`, active: pathname === page };
      }),
      { key: "history", to: history, active: pathname === history },
    );
  }

  items.push({ key: "fixtures", to: "/fixtures", active: pathname === "/fixtures" });
  if (import.meta.env.VITE_ADVICE_API_ORIGIN) {
    items.push({ key: "contribute", to: "/contribute", active: pathname === "/contribute" });
  }
  return items;
}
