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

/** One published league: its number and the tree's path under `data/`, no trailing slash. */
export interface LeagueRef {
  leagueId: number;
  path: string;
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
  return {
    leagueId: league_id as number,
    leagueName: league_name,
    season,
    gameweek: gameweek as number,
    path,
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
    const leagues = envelope.payload.leagues.map(publishedLeague);
    if (leagues.some((league) => league === null)) {
      throw new LeagueDataError(
        "The published league directory names a league it cannot describe.",
      );
    }
    return { leagues: leagues as PublishedLeague[] };
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
