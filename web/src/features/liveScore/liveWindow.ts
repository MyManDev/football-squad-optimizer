/**
 * When the live week is being played, from the site's calendar: the live week is the latest
 * gameweek whose deadline has passed, and one of its matches is being played from its kickoff
 * until `MATCH_WINDOW_MS` after it, or, while the latest live read still names it unfinished,
 * until `MATCH_WINDOW_LIMIT_MS` after it (a late kickoff or a long stoppage). With `clubs`
 * given, only those clubs' matches count: the owner's decision of 2026-11-11 is to follow
 * while one of the member's players' matches is played. The calendar is read by
 * `calendarClock`, so a device whose clock is behind does not bring a played week back. The
 * page follows the live points only while the window is open.
 */

import { calendarClock } from "../fixtures/weeks";
import type { FixturesPayload } from "../fixtures/types";

/** Ninety minutes, half time, stoppages and a margin. */
export const MATCH_WINDOW_MS = 135 * 60_000;

/** The longest a match the live read names unfinished holds the window open. */
export const MATCH_WINDOW_LIMIT_MS = 180 * 60_000;

/**
 * How often a followed page reads the live points: the forwarder keeps a played week this long.
 * Every read is a forwarder request, so a page reads only in view, only while its member's
 * matches are played, and never twice within half of this (ADR 0012, "When to revisit").
 */
export const FOLLOW_INTERVAL_MS = 60_000;

export interface LiveWindow {
  /** The latest gameweek whose deadline has passed, or null. */
  gameweek: number | null;
  /** Whether one of that week's matches is being played. */
  open: boolean;
  /** Milliseconds until `open` or the week can change, or null when nothing lies ahead. */
  changesIn: number | null;
}

/** What the member's latest live read says about the week's matches. */
export interface LiveWindowFilter {
  /** The clubs (team ids) of the member's fifteen; every club counts when it is absent. */
  clubs?: ReadonlySet<number> | null;
  /** The fixtures the live read names unfinished. */
  unfinished?: ReadonlySet<number> | null;
}

const instant = (value: string | null | undefined): number | null => {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
};

export function liveWindow(
  fixtures: FixturesPayload | null,
  now: number,
  filter: LiveWindowFilter = {},
): LiveWindow {
  if (fixtures === null) return { gameweek: null, open: false, changesIn: null };
  const clock = calendarClock(fixtures, now);
  let week: FixturesPayload["gameweeks"][number] | null = null;
  let nextDeadline: number | null = null;
  for (const candidate of fixtures.gameweeks) {
    const deadline = instant(candidate.deadline_utc);
    if (deadline === null) continue;
    if (deadline <= clock) {
      if (week === null || candidate.gameweek > week.gameweek) week = candidate;
    } else if (nextDeadline === null || deadline < nextDeadline) {
      nextDeadline = deadline;
    }
  }
  const changes: number[] = nextDeadline === null ? [] : [nextDeadline - clock];
  const { clubs, unfinished } = filter;
  let open = false;
  for (const fixture of week?.fixtures ?? []) {
    if (clubs && !clubs.has(fixture.home.team_id) && !clubs.has(fixture.away.team_id)) continue;
    const kickoff = instant(fixture.kickoff_utc);
    if (kickoff === null) continue;
    const end =
      kickoff + (unfinished?.has(fixture.fixture_id) ? MATCH_WINDOW_LIMIT_MS : MATCH_WINDOW_MS);
    if (kickoff > clock) changes.push(kickoff - clock);
    else if (clock < end) {
      open = true;
      changes.push(end - clock);
    }
  }
  return {
    gameweek: week?.gameweek ?? null,
    open,
    changesIn: changes.length === 0 ? null : Math.min(...changes),
  };
}
