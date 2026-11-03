/**
 * Whether the deadline of the gameweek a member's advice was made for has passed.
 *
 * The advice documents carry no deadline, and between a deadline and the next publish the
 * page keeps showing the plan for the week that has closed. The published fixture calendar
 * (`fixtures_v1`) states each gameweek's deadline, so the page reads it from there. A
 * calendar that is missing, unreadable, from another season or silent about this gameweek
 * says nothing, and the page then says nothing either: absent is not "still open".
 */

import { useMinuteClock } from "../../../lib/useMinuteClock";
import { useFixtures } from "../../fixtures/data";
import type { FixturesPayload } from "../../fixtures/types";

export { useMinuteClock };

/** The stated deadline of `gameweek` in `season`, or null when the calendar does not say. */
export function gameweekDeadline(
  payload: FixturesPayload | null | undefined,
  season: string | undefined,
  gameweek: number | undefined,
): string | null {
  if (!payload || season === undefined || payload.season !== season) return null;
  const week = payload.gameweeks.find((item) => item.gameweek === gameweek);
  if (!week || Number.isNaN(Date.parse(week.deadline_utc))) return null;
  return week.deadline_utc;
}

/** The deadline, once `now` has reached it; null while it is open or unknown. */
export function passedDeadline(deadlineUtc: string | null, now: number): string | null {
  return deadlineUtc !== null && now >= Date.parse(deadlineUtc) ? deadlineUtc : null;
}

/** The whole minutes left before `deadlineUtc` at `now`, rounded down; null once it is reached. */
export function minutesLeft(deadlineUtc: string, now: number): number | null {
  const left = Date.parse(deadlineUtc) - now;
  return left > 0 ? Math.floor(left / 60_000) : null;
}

/** The gameweek's deadline if it has passed, re-read once a minute so an open page notices. */
export function useDeadlinePassed(
  season: string | undefined,
  gameweek: number | undefined,
): string | null {
  const { data } = useFixtures();
  const now = useMinuteClock();
  return passedDeadline(gameweekDeadline(data, season, gameweek), now);
}
