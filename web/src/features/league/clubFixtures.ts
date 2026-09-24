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
export function clubWeeks(
  payload: FixturesPayload | null | undefined,
  season: string,
  team: string,
  gameweeks: readonly number[],
  codes: ClubCodes = clubCodesFromFixtures(payload),
): Array<ClubWeek | null> {
  if (!payload || payload.season !== season) return gameweeks.map(() => null);
  const code = clubCode(team, codes);
  const name = normalised(team);
  const isClub = (side: { name: string; short_name: string }) =>
    code !== null ? side.short_name.trim() === code : normalised(side.name) === name;
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
