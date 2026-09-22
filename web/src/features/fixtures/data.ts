import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import { withRequestDeadline } from "../../data/request";
import type { Fixture, FixtureGameweek, FixturesPayload } from "./types";

const PATH = `${import.meta.env.BASE_URL}data/fixtures.json`;

const isTeam = (value: unknown): boolean => {
  const team = value as Fixture["home"] | null;
  return (
    typeof team === "object" &&
    team !== null &&
    typeof team.name === "string" &&
    typeof team.short_name === "string"
  );
};

const isScore = (value: unknown): boolean => value === null || Number.isInteger(value);

const isFixture = (value: unknown): boolean => {
  const fixture = value as Fixture | null;
  return (
    typeof fixture === "object" &&
    fixture !== null &&
    Number.isInteger(fixture.fixture_id) &&
    (fixture.kickoff_utc === null || typeof fixture.kickoff_utc === "string") &&
    isTeam(fixture.home) &&
    isTeam(fixture.away) &&
    typeof fixture.finished === "boolean" &&
    isScore(fixture.home_score) &&
    isScore(fixture.away_score)
  );
};

const isGameweek = (value: unknown): boolean => {
  const week = value as FixtureGameweek | null;
  return (
    typeof week === "object" &&
    week !== null &&
    Number.isInteger(week.gameweek) &&
    typeof week.deadline_utc === "string" &&
    Array.isArray(week.fixtures) &&
    week.fixtures.every(isFixture)
  );
};

/**
 * The published fixture list, or `null` when this tree has none.
 *
 * Trees published before the document existed answer 404, or the host's HTML shell for
 * the unknown path. Both mean "not published", and so does a document this page cannot
 * read: the fixture list is a convenience beside the page, so it is shown or it is absent,
 * and it never puts an error on someone's squad.
 */
export async function loadFixtures(signal?: AbortSignal): Promise<FixturesPayload | null> {
  try {
    return await withRequestDeadline(
      async (deadline) => {
        const response = await fetch(PATH, { cache: "no-cache", signal: deadline });
        if (!response.ok) return null;
        const document = JSON.parse(await response.text()) as {
          contract_version?: unknown;
          payload?: FixturesPayload;
        };
        const payload = document.payload;
        if (
          document.contract_version !== "fixtures_v1" ||
          typeof payload !== "object" ||
          payload === null ||
          !(payload.current_gameweek === null || Number.isInteger(payload.current_gameweek)) ||
          !Array.isArray(payload.gameweeks) ||
          !payload.gameweeks.every(isGameweek)
        )
          return null;
        return payload;
      },
      { signal },
    );
  } catch {
    return null;
  }
}

export function useFixtures(): UseQueryResult<FixturesPayload | null> {
  return useQuery({
    queryKey: ["fixtures"],
    queryFn: ({ signal }) => loadFixtures(signal),
    staleTime: 60_000,
    retry: false,
  });
}

export interface FixtureWeeks {
  current: FixtureGameweek | null;
  next: FixtureGameweek | null;
  /** Every gameweek before the current one, newest first. */
  past: FixtureGameweek[];
}

/**
 * The rolling view needs no state of its own. The producer names `current_gameweek` from
 * the capture it published; when the run after a gameweek publishes the next number, what
 * was "next week" is read as "this week", a new week appears as next, and the week that
 * was current falls into `past` by itself.
 */
export function fixtureWeeks(payload: FixturesPayload): FixtureWeeks {
  const current = payload.current_gameweek;
  const find = (gameweek: number) =>
    payload.gameweeks.find((week) => week.gameweek === gameweek) ?? null;
  // With no open deadline the season is over: nothing is current and every week is past.
  const before = current ?? Number.POSITIVE_INFINITY;
  return {
    current: current === null ? null : find(current),
    next: current === null ? null : find(current + 1),
    past: payload.gameweeks
      .filter((week) => week.gameweek < before)
      .sort((left, right) => right.gameweek - left.gameweek),
  };
}

/** Upcoming fixtures from the published calendar, even after its capture ages.
 * No results are inferred from the clock. A missing next numbered week stays missing.
 */
export function upcomingFixtureWeeks(payload: FixturesPayload, now = Date.now()): FixtureWeeks {
  if (payload.current_gameweek === null) return fixtureWeeks(payload);
  const upcoming = [...payload.gameweeks]
    .sort((a, b) => a.gameweek - b.gameweek)
    .find(
      (week) =>
        week.gameweek >= payload.current_gameweek! &&
        (Date.parse(week.deadline_utc) > now ||
          week.fixtures.some(
            (fixture) =>
              !fixture.finished &&
              fixture.kickoff_utc !== null &&
              Date.parse(fixture.kickoff_utc) > now,
          )),
    );
  return fixtureWeeks({ ...payload, current_gameweek: upcoming?.gameweek ?? null });
}
