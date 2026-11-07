/**
 * The scoreboard and the member histories of a forwarded league, built from the members'
 * seasons and the game's events: the figures FPL states, in the shapes the published pages
 * read, with the system's own rows null and nothing projected.
 */

import { describe, expect, it } from "vitest";

import { fixtureCaptureTable, STANDINGS_EXAMPLES } from "../../../fixtures/forwarder";
import type { FixturesPayload } from "../../fixtures/types";
import type { FplEntrySeason, FplEvents, FplLeagueStandings } from "../forwarder/documents";
import { readEntrySeason, readEvents } from "../forwarder/documents";
import { checkedHistory } from "../history/historyData";
import { leagueRace } from "../race/leagueRace";
import { forwardedHistory, forwardedScoreboard } from "./forwardedScoreboard";
import { standingsMembers } from "./forwardedTree";

const CAPTURE = "fpl-live-20261016T060000Z-0123456789ab";
const TABLE = {
  contract_version: "provisional_league_ui_v1" as const,
  generated_at_utc: "2026-10-16T08:00:00Z",
  source_kind: "live" as const,
  payload: fixtureCaptureTable(CAPTURE),
};
const PAGE = STANDINGS_EXAMPLES.first_page as FplLeagueStandings;
const SOURCE_TIME = "2026-10-19T17:30:00.000Z";

/** Nine played weeks as the forwarder's synthetic season states them (fpl_entry_season_v1). */
function seasonOf(entry: number, offset = 0): FplEntrySeason {
  const weeks = Array.from({ length: 9 }, (_, index) => {
    const event = index + 1;
    const cost = event === 4 ? 4 : 0;
    return {
      event,
      points: 50 + event + offset,
      total_points: 450 + 51 * event + offset * event,
      rank: event === 1 ? null : 100_000 + event,
      overall_rank: 200_000 - event,
      event_transfers: event === 4 ? 2 : 0,
      event_transfers_cost: cost,
      bank: 5,
      value: 1000 + event,
    };
  });
  return {
    contract_version: "fpl_entry_season_v1",
    entry_id: entry,
    source_time: SOURCE_TIME,
    weeks,
    chips: [{ name: "bboost", event: 3 }],
  };
}

/** Ten gameweeks, nine finished, as fpl_events_v1 states them. */
const EVENTS: FplEvents = {
  contract_version: "fpl_events_v1",
  source_time: SOURCE_TIME,
  events: Array.from({ length: 10 }, (_, index) => {
    const id = index + 1;
    const done = id <= 9;
    return {
      id,
      finished: done,
      data_checked: done,
      average_entry_score: done ? 40 + id : 0,
      highest_score: done ? 100 + id : null,
    };
  }),
};

const FIXTURES: FixturesPayload = {
  season: TABLE.payload.season,
  source_snapshot_id: CAPTURE,
  captured_at_utc: "2026-10-16T06:00:00Z",
  current_gameweek: 9,
  unscheduled_count: 0,
  gameweeks: Array.from({ length: 12 }, (_, index) => ({
    gameweek: index + 1,
    deadline_utc: new Date(Date.UTC(2026, 7, 21 + index * 7, 17, 30)).toISOString(),
    fixtures: [],
  })),
};

describe("the forwarded documents", () => {
  it("read a season and the events, and refuse another shape", () => {
    const season = seasonOf(5001);
    expect(readEntrySeason(season, 5001)).toEqual(season);
    expect(readEntrySeason(season, 5002)).toBeNull();
    expect(readEntrySeason({ ...season, weeks: [...season.weeks].reverse() }, 5001)).toBeNull();
    expect(readEvents(EVENTS)).toEqual(EVENTS);
    expect(
      readEvents({ ...EVENTS, events: [{ ...EVENTS.events[0], finished: "true" }] }),
    ).toBeNull();
  });
});

describe("the forwarded scoreboard", () => {
  const members = PAGE.results.slice(0, 2);
  const seasons = new Map([
    [members[0]!.entry, seasonOf(members[0]!.entry, 0)],
    [members[1]!.entry, seasonOf(members[1]!.entry, 10)],
  ]);
  const board = forwardedScoreboard({
    leagueId: PAGE.league.id,
    table: TABLE,
    members,
    seasons,
    events: EVENTS,
    fixtures: FIXTURES,
  });

  it("has one week per played gameweek, with each member's gross, hit, net and total", () => {
    expect(board.payload.league_id).toBe(PAGE.league.id);
    expect(board.payload.source_snapshot_id).toBe(CAPTURE);
    expect(board.payload.gameweeks.map((week) => week.gameweek)).toEqual([
      1, 2, 3, 4, 5, 6, 7, 8, 9,
    ]);
    const fourth = board.payload.gameweeks[3]!;
    expect(fourth.members[0]).toEqual({
      entry_id: members[0]!.entry,
      points: 54,
      hit_cost: 4,
      net: 50,
      total_points: 654,
    });
    expect(fourth.members[1]!.net).toBe(60);
    expect(fourth.members_mean_net).toBe(55);
    expect(fourth.members_counted).toBe(2);
    expect(fourth.average_entry_score).toBe(44);
    expect(fourth.highest_score).toBe(104);
    expect(fourth.ours).toBeNull();
    expect(fourth.top100).toBeNull();
    expect(fourth.deadline_utc).toBe(FIXTURES.gameweeks[3]!.deadline_utc);
  });

  it("sums the settled weeks into the cumulative row", () => {
    const { cumulative } = board.payload;
    expect(cumulative.through_gameweek).toBe(9);
    expect(cumulative.gameweeks).toHaveLength(9);
    expect(cumulative.members_counted).toBe(2);
    expect(cumulative.members_mean_total_points).toBe((909 + 909 + 90) / 2);
    expect(cumulative.average_entry_score).toBe(9 * 40 + 45);
  });

  it("leaves out a member whose season was not answered, and draws the race from the rest", () => {
    const partial = forwardedScoreboard({
      leagueId: PAGE.league.id,
      table: TABLE,
      members: PAGE.results.slice(0, 3),
      seasons,
      events: EVENTS,
      fixtures: FIXTURES,
    });
    expect(partial.payload.gameweeks[0]!.members_counted).toBe(2);
    expect(partial.payload.gameweeks[0]!.members.map((row) => row.entry_id)).toEqual(
      members.map((member) => member.entry),
    );
    expect(leagueRace(partial.payload, standingsMembers([PAGE]), null)).not.toBeNull();
  });
});

describe("the forwarded history", () => {
  it("is one unrecorded week per played week, in the shape the history page checks", () => {
    const season = seasonOf(5001);
    const history = forwardedHistory({
      leagueId: PAGE.league.id,
      table: TABLE,
      season,
      fixtures: FIXTURES,
    });
    expect(() => checkedHistory(history, 5001, PAGE.league.id)).not.toThrow();
    expect(history.payload.weeks).toHaveLength(9);
    expect(history.payload.weeks[0]).toMatchObject({
      gameweek: 1,
      status: "unavailable",
      reason: "no_pre_deadline_record",
      deadline_utc: FIXTURES.gameweeks[0]!.deadline_utc,
      actual: null,
      players: [],
    });
  });
});
