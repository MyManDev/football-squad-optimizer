/**
 * Which leagues the site publishes, and where each one's tree is.
 *
 * `data/leagues.json` lists them. A site published before that file carries one league
 * under `data/league/`; that tree is read as the directory of one, so the same page serves
 * both until every publication writes the list.
 */

import type { RequestOptions } from "../../data/request";
import { LeagueDataError, LeagueDataMissing } from "./dataErrors";
import { fetchPublishedJson } from "./publishedJson";
import type { LeagueViewEnvelope } from "./types";

/**
 * The capture's device-plan table a directory line names: its path under `data/` and the
 * sha256 of its bytes. The file at a path is replaced when its capture is published again,
 * so the digest is its version.
 */
export interface DevicePlanTableRef {
  path: string;
  sha256: string;
}

/** One published league: its number and the tree's path under `data/`, no trailing slash. */
export interface LeagueRef {
  leagueId: number;
  path: string;
  /** The capture's table, where the line names one; the tree's own copy otherwise. */
  devicePlan?: DevicePlanTableRef;
}

export interface PublishedLeague extends LeagueRef {
  leagueName: string;
  season: string;
  gameweek: number;
}

export interface LeagueDirectory {
  leagues: PublishedLeague[];
}

/** The one tree a site from before the directory publishes. */
export const LEGACY_TREE_PATH = "league";

export const DIRECTORY_CONTRACT_VERSION = "league_directory_v1";

export function leagueTreePath(leagueId: number): string {
  return `leagues/${leagueId}`;
}

function fetchJson(relative: string, options?: RequestOptions): Promise<unknown> {
  return fetchPublishedJson(`${import.meta.env.BASE_URL}data/`, relative, options);
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/**
 * The table a line names, or undefined where it names none or names it unusably: the
 * league is still read, from its tree's own copy, as a line from before the table is.
 * The shipped-tree check holds every published line to this same rule.
 */
export function devicePlanTable(path: unknown, sha256: unknown): DevicePlanTableRef | undefined {
  if (
    typeof path !== "string" ||
    !/^device\/[A-Za-z0-9._-]+\/device-plan\.json$/.test(path) ||
    path.split("/").includes("..") ||
    typeof sha256 !== "string" ||
    !/^[0-9a-f]{64}$/.test(sha256)
  ) {
    return undefined;
  }
  return { path, sha256 };
}

function publishedLeague(value: unknown): PublishedLeague | null {
  if (!record(value)) return null;
  const { league_id, league_name, season, gameweek, path } = value;
  if (
    !Number.isSafeInteger(league_id) ||
    (league_id as number) <= 0 ||
    typeof league_name !== "string" ||
    typeof season !== "string" ||
    !Number.isSafeInteger(gameweek) ||
    typeof path !== "string" ||
    !/^[A-Za-z0-9_-]+(?:\/[A-Za-z0-9_-]+)*$/.test(path)
  ) {
    return null;
  }
  const devicePlan = devicePlanTable(value.device_plan, value.device_plan_sha256);
  return {
    leagueId: league_id as number,
    leagueName: league_name,
    season,
    gameweek: gameweek as number,
    path,
    ...(devicePlan === undefined ? {} : { devicePlan }),
  };
}

/**
 * The directory the site publishes, or the single legacy tree read as one. A directory
 * that lists nothing is a site with nothing to show, and says so as missing.
 */
export async function loadLeagueDirectory(options?: RequestOptions): Promise<LeagueDirectory> {
  try {
    const envelope = await fetchJson("leagues.json", options);
    if (
      !record(envelope) ||
      envelope.contract_version !== DIRECTORY_CONTRACT_VERSION ||
      !record(envelope.payload) ||
      !Array.isArray(envelope.payload.leagues)
    ) {
      throw new LeagueDataError("The published league directory is not the expected shape.");
    }
    const rows = envelope.payload.leagues;
    const valid = rows.map(publishedLeague).filter((league) => league !== null);
    const counts = new Map<number, number>();
    for (const league of valid) counts.set(league.leagueId, (counts.get(league.leagueId) ?? 0) + 1);
    // A broken row affects that league only. Duplicate identities are ambiguous, so
    // neither copy is chosen; independent leagues remain available.
    const leagues = valid.filter((league) => counts.get(league.leagueId) === 1);
    if (rows.length > 0 && leagues.length === 0) {
      throw new LeagueDataError("The published league directory has no usable league records.");
    }
    return { leagues };
  } catch (error) {
    if (!(error instanceof LeagueDataMissing)) throw error;
  }
  // No directory: the site from before it, one league under data/league/.
  const members = (await fetchJson(
    `${LEGACY_TREE_PATH}/members.json`,
    options,
  )) as LeagueViewEnvelope<{
    league_id?: unknown;
    league_name?: unknown;
    season?: unknown;
    gameweek?: unknown;
  }>;
  const payload = record(members) && record(members.payload) ? members.payload : null;
  const league = publishedLeague(
    payload && {
      league_id: payload.league_id,
      league_name: payload.league_name,
      season: payload.season,
      gameweek: payload.gameweek,
      path: LEGACY_TREE_PATH,
    },
  );
  if (league === null) throw new LeagueDataError("The published league record is invalid.");
  return { leagues: [league] };
}

export function findLeague(directory: LeagueDirectory, leagueId: number): PublishedLeague | null {
  return directory.leagues.find((league) => league.leagueId === leagueId) ?? null;
}
