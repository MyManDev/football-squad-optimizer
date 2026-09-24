import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { FixturesPayload } from "../fixtures/types";
import { clubWeeks, nextThree } from "./clubFixtures";

const published = (
  JSON.parse(readFileSync(join(__dirname, "../../../public/data/fixtures.json"), "utf-8")) as {
    payload: FixturesPayload;
  }
).payload;

function team(name: string, short: string, id: number) {
  return { team_id: id, name, short_name: short };
}

function match(id: number, home: ReturnType<typeof team>, away: ReturnType<typeof team>) {
  return {
    fixture_id: id,
    kickoff_utc: null,
    home,
    away,
    finished: false,
    home_score: null,
    away_score: null,
  };
}

const ARS = team("Arsenal", "ARS", 1);
const CHE = team("Chelsea", "CHE", 6);
const LEE = team("Leeds", "LEE", 13);

const CALENDAR: FixturesPayload = {
  season: "2026-27",
  source_snapshot_id: "test",
  captured_at_utc: "2026-09-22T00:00:00Z",
  current_gameweek: 6,
  unscheduled_count: 0,
  gameweeks: [
    { gameweek: 6, deadline_utc: "2026-10-10T10:00:00Z", fixtures: [match(1, ARS, LEE)] },
    // A double week for Arsenal, a blank one for Chelsea.
    {
      gameweek: 7,
      deadline_utc: "2026-10-17T10:00:00Z",
      fixtures: [match(2, LEE, ARS), match(3, ARS, CHE)],
    },
    { gameweek: 8, deadline_utc: "2026-10-24T10:00:00Z", fixtures: [match(4, CHE, LEE)] },
  ],
};

describe("a club's matches in a run of gameweeks", () => {
  it("finds every club of the published calendar under the name it publishes", () => {
    // Whatever the week, each side of each fixture is found, at home or away as listed.
    const week = published.gameweeks[0]!;
    for (const fixture of week.fixtures) {
      const [home] = clubWeeks(published, published.season, fixture.home.name, [week.gameweek]);
      const [away] = clubWeeks(published, published.season, fixture.away.name, [week.gameweek]);
      expect(home!.matches).toContainEqual({ opponent: fixture.away.short_name, home: true });
      expect(away!.matches).toContainEqual({ opponent: fixture.home.short_name, home: false });
    }
  });

  it("lists both matches of a double week and none of a blank one", () => {
    const arsenal = clubWeeks(CALENDAR, "2026-27", "Arsenal", [6, 7]);
    expect(arsenal[1]!.matches).toEqual([
      { opponent: "LEE", home: false },
      { opponent: "CHE", home: true },
    ]);
    const chelsea = clubWeeks(CALENDAR, "2026-27", "Chelsea", nextThree(6));
    expect(chelsea[0]).toEqual({ gameweek: 6, matches: [] });
  });

  it("finds a club published under a longer name", () => {
    const weeks = clubWeeks(CALENDAR, "2026-27", "Leeds United", [6]);
    expect(weeks[0]!.matches).toEqual([{ opponent: "ARS", home: false }]);
  });

  it("says nothing for an unlisted week, another season or no calendar", () => {
    expect(clubWeeks(CALENDAR, "2026-27", "Arsenal", [9])).toEqual([null]);
    expect(clubWeeks(CALENDAR, "2025-26", "Arsenal", [6])).toEqual([null]);
    expect(clubWeeks(null, "2026-27", "Arsenal", [6, 7])).toEqual([null, null]);
  });
});
