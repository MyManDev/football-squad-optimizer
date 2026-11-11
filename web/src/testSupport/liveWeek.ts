/**
 * A synthetic live week shaped like GW10 for the LIVE page's tests: fifteen picks of seven
 * invented clubs, three matches on a Saturday, and every input the board reads (the live
 * document, its event detail, the member's week, the capture's table and the calendar).
 * Each test changes only what it is about. Never a member capture.
 */

import type { FixturesPayload } from "../features/fixtures/types";
import type { LiveActivity } from "../features/liveScore/weekActivity";
import type { MemberWeek, Position, WeekLive } from "../features/liveScore/weekLive";
import type { DevicePlanDocument } from "../features/league/device/types";
import type { LiveBoardInput } from "../features/league/live/liveBoard";

export const TEST_SEASON = "2026-27";
export const TEST_WEEK = 10;

/** One pick: his position and club, and what the live read says of him. */
export interface TestPick {
  id: number;
  position: Position;
  club: number;
  points: number;
  minutes: number;
  card: boolean;
}

export interface TestFixture {
  id: number;
  home: number;
  away: number;
  kickoff: string | null;
  finished: boolean;
}

/** GK, four defenders, four midfielders and two forwards, then a keeper and three reserves. */
export function testPicks(): TestPick[] {
  const pick = (id: number, position: Position, club: number): TestPick => ({
    id,
    position,
    club,
    points: 0,
    minutes: 0,
    card: false,
  });
  return [
    pick(1, "GK", 1),
    pick(2, "DEF", 1),
    pick(3, "DEF", 2),
    pick(4, "DEF", 3),
    pick(5, "DEF", 4),
    pick(6, "MID", 1),
    pick(7, "MID", 2),
    pick(8, "MID", 3),
    pick(9, "MID", 5),
    pick(10, "FWD", 2),
    pick(11, "FWD", 4),
    pick(12, "GK", 3),
    pick(13, "DEF", 5),
    pick(14, "MID", 6),
    pick(15, "FWD", 6),
  ];
}

/** Saturday's three matches: 12:30, 15:00 and 17:30 UTC. */
export function testFixtures(): TestFixture[] {
  return [
    { id: 101, home: 1, away: 2, kickoff: "2026-11-21T12:30:00Z", finished: false },
    { id: 102, home: 3, away: 4, kickoff: "2026-11-21T15:00:00Z", finished: false },
    { id: 103, home: 5, away: 6, kickoff: "2026-11-21T17:30:00Z", finished: false },
  ];
}

const clubName = (club: number) => `Club ${club}`;
const clubCode = (club: number) => `C${club}`;
const team = (club: number) => ({
  team_id: club,
  name: clubName(club),
  short_name: clubCode(club),
});

export interface TestWeek {
  picks?: TestPick[];
  fixtures?: TestFixture[];
  sourceTime?: string;
  activity?: LiveActivity | null;
  member?: Partial<MemberWeek>;
  /** Players beyond the picks, each in the live read and the table: a rival's own picks. */
  others?: TestPick[];
}

/** Every input of `liveBoard` for the week described. */
export function testWeek({
  picks = testPicks(),
  fixtures = testFixtures(),
  sourceTime = "2026-11-21T15:30:00Z",
  activity = null,
  member = {},
  others = [],
}: TestWeek = {}): LiveBoardInput {
  const everyone = [...picks, ...others];
  const live: WeekLive = {
    contract_version: "week_live_v1",
    season: TEST_SEASON,
    gameweek: TEST_WEEK,
    source_time: sourceTime,
    fixtures: fixtures.map((fixture) => ({
      id: fixture.id,
      home_club: fixture.home,
      away_club: fixture.away,
      finished: fixture.finished,
    })),
    elements: everyone.map((row) => ({
      element_id: row.id,
      points: row.points,
      minutes: row.minutes,
      card_shown: row.card,
    })),
  };
  const table: DevicePlanDocument = {
    contract_version: "league_device_plan_v2",
    season: TEST_SEASON,
    gameweek: TEST_WEEK + 1,
    source_snapshot_id: "synthetic-live-capture",
    policy_id: "member_planning_policy_v2",
    rules: {
      squad_size: 15,
      starting_size: 11,
      squad_position_limits: { GK: 2, DEF: 5, MID: 5, FWD: 3 },
      starting_position_min: { GK: 1, DEF: 3, MID: 2, FWD: 1 },
      starting_position_max: { GK: 1, DEF: 5, MID: 5, FWD: 3 },
      max_players_per_team: 3,
      max_free_transfers: 5,
      hit_cost_scaled: 8000,
      hit_points_charged: 4,
      expected_points_scale: 1000,
      chips: [],
      transfers_cap: null,
    },
    players: everyone.map((row) => ({
      id: 9000 + row.id,
      element_id: row.id,
      name: `Player Number${row.id}`,
      short_name: `P${row.id}`,
      team: clubName(row.club),
      position: row.position,
      buy_tenths: 50,
      start_tenths: 50,
      expected_points: 2,
      coefficients: [200, 1800, 2000],
    })),
  };
  // Every club the picks name is in the calendar; a club without a match this week plays
  // in the next one.
  const clubs = new Set(everyone.map((row) => row.club));
  const playing = new Set(fixtures.flatMap((fixture) => [fixture.home, fixture.away]));
  const idle = [...clubs].filter((club) => !playing.has(club));
  const calendar: FixturesPayload = {
    season: TEST_SEASON,
    source_snapshot_id: "synthetic-calendar",
    captured_at_utc: "2026-11-20T09:00:00Z",
    current_gameweek: TEST_WEEK + 1,
    unscheduled_count: 0,
    gameweeks: [
      {
        gameweek: TEST_WEEK,
        deadline_utc: "2026-11-21T11:00:00Z",
        fixtures: fixtures.map((fixture) => ({
          fixture_id: fixture.id,
          kickoff_utc: fixture.kickoff,
          home: team(fixture.home),
          away: team(fixture.away),
          finished: fixture.finished,
          home_score: null,
          away_score: null,
        })),
      },
      {
        gameweek: TEST_WEEK + 1,
        deadline_utc: "2026-11-28T11:00:00Z",
        fixtures: idle.map((club, index) => ({
          fixture_id: 900 + index,
          kickoff_utc: "2026-11-28T15:00:00Z",
          home: team(club),
          away: team(club === 1 ? 2 : 1),
          finished: false,
          home_score: null,
          away_score: null,
        })),
      },
    ],
  };
  return {
    live,
    activity,
    table,
    fixtures: calendar,
    member: {
      entry_id: 101,
      gameweek: TEST_WEEK,
      pick_order: picks.map((row) => row.id),
      captain: 10,
      vice: 7,
      active_chip: null,
      transfer_cost: 0,
      ...member,
    },
  };
}

/** Event detail for the week: each element's minutes in each of his club's fixtures. */
export function testActivity(
  input: LiveBoardInput,
  {
    inPlay = [],
    minutes = {},
    goals = {},
    assists = {},
  }: {
    inPlay?: number[];
    /** Per element, his minutes in each fixture by id; a single fixture gets all of them. */
    minutes?: Record<number, Record<number, number>>;
    goals?: Record<number, number>;
    assists?: Record<number, number>;
  } = {},
): LiveActivity {
  const clubs = new Map(
    input.table.players.map((player) => [player.element_id, Number(player.team.slice(5))]),
  );
  const appearances = input.live.elements.flatMap((element) => {
    const club = clubs.get(element.element_id)!;
    const own = input.live.fixtures.filter(
      (fixture) => fixture.home_club === club || fixture.away_club === club,
    );
    return own.map((fixture, index) => ({
      element_id: element.element_id,
      fixture_id: fixture.id,
      minutes: minutes[element.element_id]?.[fixture.id] ?? (index === 0 ? element.minutes : 0),
      goals: index === 0 ? (goals[element.element_id] ?? 0) : 0,
      assists: index === 0 ? (assists[element.element_id] ?? 0) : 0,
    }));
  });
  return { in_play_fixtures: inPlay, appearances };
}
