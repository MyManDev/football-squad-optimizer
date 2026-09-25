import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { FixturesPayload } from "../fixtures/types";
import { clubWeeks, listedWeeks, meetings, nextThree } from "./clubFixtures";

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

describe("the weeks the calendar lists", () => {
  it("keeps the listed weeks in order and leaves out the rest", () => {
    expect(listedWeeks(CALENDAR, "2026-27", nextThree(6))).toEqual([6, 7, 8]);
    expect(listedWeeks(CALENDAR, "2026-27", nextThree(7))).toEqual([7, 8]);
    expect(listedWeeks(CALENDAR, "2025-26", nextThree(6))).toEqual([]);
    expect(listedWeeks(null, "2026-27", nextThree(6))).toEqual([]);
  });
});

describe("players of one eleven who face each other", () => {
  const eleven = [
    { name: "Raya", team: "Arsenal" },
    { name: "Saka", team: "Arsenal" },
    { name: "Calvert-Lewin", team: "Leeds United" },
    { name: "Palmer", team: "Chelsea" },
  ];

  it("pairs the two sides of a fixture, home first, from the calendar alone", () => {
    expect(meetings(CALENDAR, "2026-27", 6, eleven)).toEqual([
      {
        home: "ARS",
        away: "LEE",
        homePlayers: [eleven[0], eleven[1]],
        awayPlayers: [eleven[2]],
      },
    ]);
    // Both of Arsenal's matches in the double week meet a side of the eleven.
    expect(meetings(CALENDAR, "2026-27", 7, eleven).map((m) => `${m.home}-${m.away}`)).toEqual([
      "LEE-ARS",
      "ARS-CHE",
    ]);
  });

  it("names no meeting where only one side is in the eleven, or without the week", () => {
    expect(meetings(CALENDAR, "2026-27", 8, eleven.slice(0, 2))).toEqual([]);
    expect(meetings(CALENDAR, "2026-27", 9, eleven)).toEqual([]);
    expect(meetings(null, "2026-27", 6, eleven)).toEqual([]);
  });

  it("finds the real GW6 meetings of the published calendar", () => {
    const week = published.current_gameweek!;
    const first = published.gameweeks.find((item) => item.gameweek === week)!.fixtures[0]!;
    const players = [
      { name: "home", team: first.home.name },
      { name: "away", team: first.away.name },
    ];
    expect(meetings(published, published.season, week, players)).toEqual([
      {
        home: first.home.short_name,
        away: first.away.short_name,
        homePlayers: [players[0]],
        awayPlayers: [players[1]],
      },
    ]);
  });
});
