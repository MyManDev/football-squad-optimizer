/**
 * When the live week is being played, from the site's calendar: the live week is the latest
 * gameweek whose deadline has passed, and one of its matches is being played from its kickoff
 * until `MATCH_WINDOW_MS` after it. The page follows the live points only then.
 */

import type { FixturesPayload } from "../fixtures/types";

/** Ninety minutes, half time, stoppages and a margin. */
export const MATCH_WINDOW_MS = 135 * 60_000;

/** How often a followed page reads the live points: the forwarder keeps a played week this long. */
export const FOLLOW_INTERVAL_MS = 60_000;

export interface LiveWindow {
  /** The latest gameweek whose deadline has passed, or null. */
  gameweek: number | null;
  /** Whether one of that week's matches is being played. */
  open: boolean;
  /** Milliseconds until `open` or the week can change, or null when nothing lies ahead. */
  changesIn: number | null;
}

const instant = (value: string | null | undefined): number | null => {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
};

export function liveWindow(fixtures: FixturesPayload | null, now: number): LiveWindow {
  if (fixtures === null) return { gameweek: null, open: false, changesIn: null };
  let week: FixturesPayload["gameweeks"][number] | null = null;
  let nextDeadline: number | null = null;
  for (const candidate of fixtures.gameweeks) {
    const deadline = instant(candidate.deadline_utc);
    if (deadline === null) continue;
    if (deadline <= now) {
      if (week === null || candidate.gameweek > week.gameweek) week = candidate;
    } else if (nextDeadline === null || deadline < nextDeadline) {
      nextDeadline = deadline;
    }
  }
  const changes: number[] = nextDeadline === null ? [] : [nextDeadline - now];
  let open = false;
  for (const fixture of week?.fixtures ?? []) {
    const kickoff = instant(fixture.kickoff_utc);
    if (kickoff === null) continue;
    const end = kickoff + MATCH_WINDOW_MS;
    if (kickoff > now) changes.push(kickoff - now);
    else if (now < end) {
      open = true;
      changes.push(end - now);
    }
  }
  return {
    gameweek: week?.gameweek ?? null,
    open,
    changesIn: changes.length === 0 ? null : Math.min(...changes),
  };
}
