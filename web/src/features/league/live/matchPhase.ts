/**
 * Where a match of the live week stands at a read's source time: one rule for every place
 * that groups or counts the week's matches, so the member's live card and the LIVE page
 * never state two counts for the same read.
 *
 * A match has started once FPL lists it in play or someone has played in it (with no event
 * detail: its kickoff has passed and someone has played for one of its clubs), and past its
 * window only a match that started is over; one that never did (put back, or moved within
 * the day) is still to come. A pick's own minutes in it mean it has started. The window
 * still ends a started match: FPL lists a match in play, and leaves `finished` false, until
 * its bonus is checked, an hour or more after the final whistle.
 */

import type { FixturesPayload } from "../../fixtures/types";
import { MATCH_WINDOW_MS } from "../../liveScore/liveWindow";
import type { LiveActivity } from "../../liveScore/weekActivity";
import type { WeekLive } from "../../liveScore/weekLive";
import { forecastSource } from "../device/chipForecast/member";
import type { DevicePlanDocument } from "../device/types";

/** Where a match stands at the read's source time. */
export type LivePhase = "upcoming" | "playing" | "finished";

export interface MatchPhaseInput {
  live: WeekLive;
  activity: LiveActivity | null;
  table: DevicePlanDocument;
  fixtures: FixturesPayload;
}

/** Reads one fixture's phase; `minutes` are a pick's own minutes in it, where they are known. */
export type MatchPhaseReader = (
  fixture: WeekLive["fixtures"][number],
  minutes: number | null,
) => LivePhase;

const instant = (value: string | null | undefined): number | null => {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
};

export function matchPhaseReader({
  live,
  activity,
  table,
  fixtures,
}: MatchPhaseInput): MatchPhaseReader {
  const time = Date.parse(live.source_time);
  const kickoffs = new Map<number, number | null>();
  for (const week of fixtures.gameweeks) {
    for (const fixture of week.fixtures) {
      kickoffs.set(fixture.fixture_id, instant(fixture.kickoff_utc));
    }
  }
  const inPlay = new Set(activity?.in_play_fixtures ?? []);
  // The fixtures someone has played minutes in, where the read has detail; where it has none,
  // the clubs someone has played for in the week.
  const playedIn = new Set<number>();
  for (const row of activity?.appearances ?? []) if (row.minutes > 0) playedIn.add(row.fixture_id);
  const clubsPlayed = new Set<number>();
  if (activity === null) {
    const clubIds = forecastSource(fixtures)?.club_ids_by_name;
    const players = new Map(table.players.map((player) => [player.element_id, player]));
    for (const element of live.elements) {
      const team = element.minutes > 0 ? players.get(element.element_id)?.team : undefined;
      const club = team === undefined ? undefined : clubIds?.get(team);
      if (club !== undefined) clubsPlayed.add(club);
    }
  }
  return (fixture, minutes) => {
    const kickoff = kickoffs.get(fixture.id) ?? null;
    const started =
      (activity !== null
        ? inPlay.has(fixture.id) || playedIn.has(fixture.id)
        : kickoff !== null &&
          time >= kickoff &&
          (clubsPlayed.has(fixture.home_club) || clubsPlayed.has(fixture.away_club))) ||
      (minutes ?? 0) > 0;
    if (fixture.finished) return "finished";
    if (kickoff !== null && time >= kickoff + MATCH_WINDOW_MS) {
      return started ? "finished" : "upcoming";
    }
    return started ? "playing" : "upcoming";
  };
}

/** How many of the week's matches are over at the read's source time. */
export function matchesOver(input: MatchPhaseInput): number {
  const phaseOf = matchPhaseReader(input);
  return input.live.fixtures.filter((fixture) => phaseOf(fixture, null) === "finished").length;
}
