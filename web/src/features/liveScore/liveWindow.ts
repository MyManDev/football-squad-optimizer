/**
 * When the live week is being played, from the site's calendar: the live week is the latest
 * gameweek whose deadline has passed, and one of its matches is being played from its kickoff
 * until `MATCH_WINDOW_MS` after it, or, while the latest live read still sees it played,
 * until `MATCH_WINDOW_LIMIT_MS` after it (a late kickoff or a long stoppage). With `clubs`
 * given, only those clubs' matches count: the owner's decision of 2026-11-11 is to follow
 * while one of the member's players' matches is played. The calendar is read by
 * `calendarClock`, so a device whose clock is behind does not bring a played week back. The
 * page follows the live points only while the window is open.
 */

import { weekState, WEEK_MATCH_LIMIT_MS, type WeekEvent } from "../../lib/weekState";
import type { FixturesPayload } from "../fixtures/types";

/** Ninety minutes, half time, stoppages and a margin. */
export const MATCH_WINDOW_MS = 135 * 60_000;

/** The longest a match the live read names unfinished holds the window open. */
export const MATCH_WINDOW_LIMIT_MS = WEEK_MATCH_LIMIT_MS;

/**
 * How often a followed page reads the live points: the forwarder keeps a played week this long.
 * Every read is a forwarder request, so a page reads only in view, only while its member's
 * matches are played, and never twice within half of this (ADR 0012, "When to revisit").
 */
export const FOLLOW_INTERVAL_MS = 60_000;

/**
 * How often a page reads while none of its member's matches is open but one may still be played:
 * FPL has not finished it, its minutes stand still, and its window's limit has not come.
 */
export const SLOW_FOLLOW_MS = 5 * 60_000;

export interface LiveWindow {
  /** The latest gameweek whose deadline has passed, or null. */
  gameweek: number | null;
  /** Whether one of that week's matches is being played. */
  open: boolean;
  /**
   * Whether, with no match open, one whose minutes stood still (a long stoppage, a stalled feed)
   * may still be played until its limit: the page reads now and then (`SLOW_FOLLOW_MS`).
   */
  slow: boolean;
  /** Milliseconds until a member window or shared policy boundary, or null when none lies ahead. */
  changesIn: number | null;
}

/** What the member's latest live read says about the week's matches. */
export interface LiveWindowFilter {
  /** The clubs (team ids) of the member's fifteen; every club counts when it is absent. */
  clubs?: ReadonlySet<number> | null;
  /** The fixtures the live read names still played. */
  unfinished?: ReadonlySet<number> | null;
  /** The fixtures FPL has not finished whose minutes stood still at the latest read. */
  stalled?: ReadonlySet<number> | null;
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
  events: readonly WeekEvent[] = [],
): LiveWindow {
  if (fixtures === null) return { gameweek: null, open: false, slow: false, changesIn: null };
  const state = weekState({ treeGameweek: null, events, fixtures, now });
  const clock = state.clock;
  const week = fixtures.gameweeks.find((row) => row.gameweek === state.weeks.memberScore);
  const changes: number[] = state.changesIn === null ? [] : [state.changesIn];
  const { clubs, unfinished, stalled } = filter;
  let open = false;
  let slow = false;
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
    } else if (stalled?.has(fixture.fixture_id) && clock < kickoff + MATCH_WINDOW_LIMIT_MS) {
      slow = true;
      changes.push(kickoff + MATCH_WINDOW_LIMIT_MS - clock);
    }
  }
  return {
    gameweek: state.weeks.memberScore,
    open: state.weeks.pill !== null && open,
    slow: state.weeks.pill !== null && slow && !open,
    changesIn: changes.length === 0 ? null : Math.min(...changes),
  };
}

/**
 * Whether LIVE follows a week now (the owner's request of 2026-11-17: LIVE is for following
 * the matches, not for reading a played week). A week is on from its first kickoff until
 * `MATCH_WINDOW_LIMIT_MS` after its last, every club counted. Otherwise LIVE waits for the
 * next week to start: the live week itself when its first match is still to come, else the
 * next listed gameweek, including a blank one. An undated assigned match can keep the
 * calendar on N, while LIVE still stops at its last known kickoff plus 180 minutes.
 */
export interface LivePhase {
  on: boolean;
  /** The week LIVE waits for, while it is not on; null when the calendar names none. */
  nextGameweek: number | null;
  /** That week's first kickoff, in milliseconds since the epoch. */
  nextKickoff: number | null;
  /** Milliseconds until the next shared policy boundary, or null when none lies ahead. */
  changesIn: number | null;
}

export function livePhase(
  fixtures: FixturesPayload | null,
  now: number,
  events: readonly WeekEvent[] = [],
): LivePhase {
  const state = weekState({ treeGameweek: null, events, fixtures, now });
  return {
    on: state.weeks.live !== null,
    nextGameweek: state.weeks.liveWaiting,
    nextKickoff: state.nextKickoff,
    changesIn: state.changesIn,
  };
}
