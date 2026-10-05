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

export function memberHistoryAddress(leagueId: number, entryId: number | string): string {
  return `${memberAddress(leagueId, entryId)}/history`;
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
