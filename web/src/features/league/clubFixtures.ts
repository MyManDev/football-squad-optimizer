/**
 * A club's matches in a run of gameweeks, read from the published fixture calendar.
 *
 * A player record names its club the way the game displays it ('Man Utd'); the calendar
 * names both sides of every fixture with a name and a short name. The club is found by its
 * code where one is known (the calendar's own short name first, the season's static map
 * second) and by its name otherwise, so a long name a document might use still meets the
 * calendar's short one. Nothing here rates a fixture: a match is an opponent and a venue.
 */

import { clubCode, clubCodesFromFixtures, type ClubCodes } from "../../lib/clubs";
import type { FixturesPayload } from "../fixtures/types";

export interface ClubMatch {
  /** The opponent's short name as the calendar prints it. */
  opponent: string;
  home: boolean;
}

/**
 * One gameweek of one club: every opponent in a double week, none in a blank one. A week
 * the calendar does not list at all is `null` in the result, because an unlisted week is
 * not a blank week.
 */
export interface ClubWeek {
  gameweek: number;
  matches: ClubMatch[];
}

const normalised = (name: string) => name.trim().toLocaleLowerCase("en-GB");

/**
 * The club's matches in each of `gameweeks`, in that order. With no calendar, or a
 * calendar from another season, every week is unknown (`null`): the page then shows no
 * fixture rather than another season's.
 */
/** Whether a fixture side is the club, by code where one is known and by name otherwise. */
function sideMatcher(team: string, codes: ClubCodes) {
  const code = clubCode(team, codes);
  const name = normalised(team);
  return (side: { name: string; short_name: string }) =>
    code !== null ? side.short_name.trim() === code : normalised(side.name) === name;
}

export function clubWeeks(
  payload: FixturesPayload | null | undefined,
  season: string,
  team: string,
  gameweeks: readonly number[],
  codes: ClubCodes = clubCodesFromFixtures(payload),
): Array<ClubWeek | null> {
  if (!payload || payload.season !== season) return gameweeks.map(() => null);
  const isClub = sideMatcher(team, codes);
  return gameweeks.map((gameweek) => {
    const week = payload.gameweeks.find((item) => item.gameweek === gameweek);
    if (!week) return null;
    const matches: ClubMatch[] = [];
    for (const fixture of week.fixtures) {
      if (isClub(fixture.home)) matches.push({ opponent: fixture.away.short_name, home: true });
      else if (isClub(fixture.away))
        matches.push({ opponent: fixture.home.short_name, home: false });
    }
    return { gameweek, matches };
  });
}

/** The gameweek and the two after it: the run the boards and the fixture rail print. */
export function nextThree(gameweek: number): number[] {
  return [gameweek, gameweek + 1, gameweek + 2];
}

/**
 * The weeks of `gameweeks` the calendar lists, in order. A week it does not list is left
 * out rather than shown as a blank week; with no calendar, or another season's, none is.
 */
export function listedWeeks(
  payload: FixturesPayload | null | undefined,
  season: string,
  gameweeks: readonly number[],
): number[] {
  if (!payload || payload.season !== season) return [];
  return gameweeks.filter((gameweek) =>
    payload.gameweeks.some((week) => week.gameweek === gameweek),
  );
}

/** One fixture of a gameweek in which players of the eleven stand on both sides. */
export interface Meeting<P> {
  home: string;
  away: string;
  homePlayers: P[];
  awayPlayers: P[];
}

/**
 * The fixtures of `gameweek` that set players of `players` against each other, in the
 * calendar's order, each side named by its short name. Read from the fixture list alone:
 * a meeting is a fact about the calendar, not a rating of it.
 */
export function meetings<P extends { team: string }>(
  payload: FixturesPayload | null | undefined,
  season: string,
  gameweek: number,
  players: readonly P[],
  codes: ClubCodes = clubCodesFromFixtures(payload),
): Meeting<P>[] {
  if (!payload || payload.season !== season) return [];
  const week = payload.gameweeks.find((item) => item.gameweek === gameweek);
  if (!week) return [];
  const matchers = players.map((player) => ({ player, isClub: sideMatcher(player.team, codes) }));
  const on = (side: { name: string; short_name: string }) =>
    matchers.filter(({ isClub }) => isClub(side)).map(({ player }) => player);
  return week.fixtures
    .map((fixture) => ({
      home: fixture.home.short_name,
      away: fixture.away.short_name,
      homePlayers: on(fixture.home),
      awayPlayers: on(fixture.away),
    }))
    .filter((meeting) => meeting.homePlayers.length > 0 && meeting.awayPlayers.length > 0);
}
