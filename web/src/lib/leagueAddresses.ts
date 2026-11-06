/**
 * The addresses of the league pages, written once. The league number is in every address
 * under /league: the number chooses the league, the rest of the address names the page.
 */

export const LEAGUE_ROOT = "/league";

export function leagueAddress(leagueId: number): string {
  return `${LEAGUE_ROOT}/${leagueId}`;
}

export function membersAddress(leagueId: number): string {
  return `${leagueAddress(leagueId)}/members`;
}

/** A member's decision page; `search` is a query string with its leading '?', or "". */
export function memberAddress(leagueId: number, entryId: number | string, search = ""): string {
  return `${membersAddress(leagueId)}/${entryId}${search}`;
}

/**
 * One FPL team's page on its own, read through the forwarder (#983 step 4): no league
 * number, since the team is not opened from a league.
 */
export function entryAddress(entryId: number | string): string {
  return `/entry/${entryId}`;
}

export function memberHistoryAddress(leagueId: number, entryId: number | string): string {
  return `${memberAddress(leagueId, entryId)}/history`;
}

/**
 * The member's tools, each a page of its own under the member's page that the sidebar
 * links once the visitor has said who they are: the squad held now, the what-if squad, the duel, the chips and free transfers, and the squad card.
 */
export const MEMBER_TOOLS = ["current-squad", "what-if", "duel", "chips", "card"] as const;

export type MemberTool = (typeof MEMBER_TOOLS)[number];

export function isMemberTool(value: string | undefined): value is MemberTool {
  return (MEMBER_TOOLS as readonly (string | undefined)[]).includes(value);
}

/** A member's tool page; `search` carries the plan, as on the decision page. */
export function memberToolAddress(
  leagueId: number,
  entryId: number | string,
  tool: MemberTool,
  search = "",
): string {
  return `${memberAddress(leagueId, entryId)}/${tool}${search}`;
}

/** The league number an address under /league names, or null where it names none. */
export function leagueIdInAddress(pathname: string): number | null {
  const match = /^\/league\/(\d+)(?:\/|$)/.exec(pathname);
  if (!match) return null;
  const id = Number(match[1]);
  return Number.isSafeInteger(id) && id > 0 ? id : null;
}

/**
 * Where an address from before the league number lived: `/league/members/...` becomes the
 * same page under the given league. Null for an address that already names a league or is
 * not a league page.
 */
export function legacyLeagueAddress(pathname: string, leagueId: number): string | null {
  if (leagueIdInAddress(pathname) !== null) return null;
  if (pathname === LEAGUE_ROOT || pathname === `${LEAGUE_ROOT}/`) return leagueAddress(leagueId);
  const rest = /^\/league\/(members(?:\/.*)?)$/.exec(pathname);
  return rest ? `${leagueAddress(leagueId)}/${rest[1]}` : null;
}

/**
 * What a navigation asks of the "Sen kimsin?" step, carried in the router's state (which
 * a reload keeps). `FIND_YOURSELF`: once the visitor has said who they are, open their own
 * page. `PICK_HERE`: open the address they are on.
 */
export const FIND_YOURSELF = { identity: "find" } as const;
export const PICK_HERE = { identity: "here" } as const;
export type IdentityStep = typeof FIND_YOURSELF | typeof PICK_HERE;

function identityStep(state: unknown): unknown {
  return typeof state === "object" && state !== null
    ? (state as { identity?: unknown }).identity
    : undefined;
}

/** The navigation asked for the visitor's own page once they say who they are. */
export function asksForOwnPage(state: unknown): boolean {
  return identityStep(state) === FIND_YOURSELF.identity;
}

/** The navigation came to the step on purpose, so the step takes focus. */
export function arrivedToPick(state: unknown): boolean {
  const step = identityStep(state);
  return step === FIND_YOURSELF.identity || step === PICK_HERE.identity;
}
