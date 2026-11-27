/** What the fixtures page reads out of the published calendar: nothing here loads or draws. */

import { calendarClock, weekState, type WeekEvent } from "../../lib/weekState";
import type { Fixture, FixtureGameweek, FixtureTeam, FixturesPayload } from "./types";

export { calendarClock };

/** How many gameweeks the matrix shows: the upcoming one and the four after it. */
const GENERAL_WEEKS = 5;

const stillToKickOff = (fixture: Fixture, clock: number): boolean =>
  !fixture.finished && fixture.kickoff_utc !== null && Date.parse(fixture.kickoff_utc) > clock;

/**
 * The shared policy's fixture target and every listed week after it. The last kickoff
 * does not remove a week while its match window remains. An assigned undated match can
 * retain N until a flag or the next deadline resolves it; missing weeks are not invented.
 */
export function weeksAhead(
  payload: FixturesPayload,
  now = Date.now(),
  events: readonly WeekEvent[] = [],
): FixtureGameweek[] {
  const first = weekState({ treeGameweek: null, events, fixtures: payload, now }).weeks.fixtures;
  return first === null
    ? []
    : payload.gameweeks
        .filter((week) => week.gameweek >= first)
        .sort((left, right) => left.gameweek - right.gameweek);
}

/**
 * The matrix's window, which rolls on by itself as `weeksAhead` does. A number the calendar does
 * not list stays missing.
 */
export function generalWeeks(ahead: readonly FixtureGameweek[]): FixtureGameweek[] {
  const first = ahead[0]?.gameweek ?? 0;
  return ahead.filter((week) => week.gameweek < first + GENERAL_WEEKS);
}

/** Every club the calendar names, once each, in the order of their codes. */
export function fixtureClubs(payload: FixturesPayload): FixtureTeam[] {
  const clubs = new Map<string, FixtureTeam>();
  for (const week of payload.gameweeks) {
    for (const fixture of week.fixtures) {
      clubs.set(fixture.home.short_name, fixture.home);
      clubs.set(fixture.away.short_name, fixture.away);
    }
  }
  return [...clubs.values()].sort((left, right) => (left.short_name < right.short_name ? -1 : 1));
}

/** A fixture from one club's side. */
export interface ClubFixture {
  fixture: Fixture;
  opponent: FixtureTeam;
  home: boolean;
  /** Played, or past its kickoff though the capture has no result yet. */
  behind: boolean;
}

function clubFixtures(week: FixtureGameweek, code: string, clock: number): ClubFixture[] {
  return week.fixtures.flatMap((fixture) => {
    const home = fixture.home.short_name === code;
    if (!home && fixture.away.short_name !== code) return [];
    const toCome =
      stillToKickOff(fixture, clock) || (!fixture.finished && fixture.kickoff_utc === null);
    return [{ fixture, opponent: home ? fixture.away : fixture.home, home, behind: !toCome }];
  });
}

/** One club's line of the matrix: its fixtures in each of the weeks, in their order. */
export interface ClubLine {
  club: FixtureTeam;
  cells: ClubFixture[][];
}

/** Every club's line over `weeks`. An empty cell is a week that club does not play. */
export function clubMatrix(
  payload: FixturesPayload,
  weeks: readonly FixtureGameweek[],
  now = Date.now(),
): ClubLine[] {
  const clock = calendarClock(payload, now);
  return fixtureClubs(payload).map((club) => ({
    club,
    cells: weeks.map((week) => clubFixtures(week, club.short_name, clock)),
  }));
}

/** One club's matches of a gameweek still to come; none at all is a week it does not play. */
export interface ClubWeekAhead {
  gameweek: number;
  matches: ClubFixture[];
}

/**
 * A club's matches still to come, week by week. A week in which it has already played is left
 * out, since it is no blank week: the match is simply behind it. A fixture with no date is
 * still to come.
 */
export function clubWeeksAhead(
  payload: FixturesPayload,
  code: string,
  now = Date.now(),
): ClubWeekAhead[] {
  const clock = calendarClock(payload, now);
  return weeksAhead(payload, now).flatMap((week) => {
    const own = clubFixtures(week, code, clock);
    const matches = own.filter((match) => !match.behind);
    return own.length > 0 && matches.length === 0 ? [] : [{ gameweek: week.gameweek, matches }];
  });
}
