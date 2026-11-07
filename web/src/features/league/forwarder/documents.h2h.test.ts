/**
 * The head-to-head documents the forwarder answers with, read as the other documents are:
 * every field its contract names, and the identities asked for; anything else reads as null.
 */

import { describe, expect, it } from "vitest";

import {
  readH2hMatches,
  readH2hStandings,
  tableRows,
  type FplH2hMatches,
  type FplH2hStandings,
} from "./documents";

const CUP: FplH2hStandings = {
  contract_version: "fpl_h2h_standings_v1",
  league: { id: 4242, name: "Synthetic Cup", scoring: "h2h" },
  page: 1,
  has_next: false,
  source_time: "2026-10-19T17:30:00.000Z",
  results: [
    {
      entry: 7001,
      entry_name: "Cup Team 1",
      player_name: "Cup Manager 1",
      rank: 1,
      rank_sort: 1,
      last_rank: null,
      total: 27,
      matches_played: 9,
      matches_won: 9,
      matches_drawn: 0,
      matches_lost: 0,
      points_for: 600,
    },
    {
      entry: 7002,
      entry_name: "Cup Team 2",
      player_name: "Cup Manager 2",
      rank: 2,
      rank_sort: 2,
      last_rank: 3,
      total: 24,
      matches_played: 9,
      matches_won: 8,
      matches_drawn: 0,
      matches_lost: 1,
      points_for: 593,
    },
  ],
};

const WEEK: FplH2hMatches = {
  contract_version: "fpl_h2h_matches_v1",
  league: { id: 4242, scoring: "h2h" },
  gameweek: 9,
  page: 1,
  has_next: false,
  source_time: "2026-10-19T17:30:00.000Z",
  results: [
    {
      id: 9000,
      entry_1: { entry: 7001, name: "Cup Team 1", player_name: "Cup Manager 1", points: 60 },
      entry_2: { entry: 7002, name: "Cup Team 2", player_name: "Cup Manager 2", points: 50 },
      winner: 7001,
      started: true,
      finished: true,
    },
    {
      id: 9001,
      entry_1: { entry: 7003, name: "Cup Team 3", player_name: "Cup Manager 3", points: 61 },
      entry_2: { entry: null, name: "AVERAGE", player_name: "AVERAGE", points: 51 },
      winner: 7003,
      started: true,
      finished: true,
    },
  ],
};

describe("a head-to-head table", () => {
  it("reads when it is the league's and the page's, and refuses another", () => {
    expect(readH2hStandings(CUP, 4242, 1)).toEqual(CUP);
    expect(readH2hStandings(CUP, 4243, 1)).toBeNull();
    expect(readH2hStandings(CUP, 4242, 2)).toBeNull();
    expect(
      readH2hStandings({ ...CUP, league: { ...CUP.league, scoring: "classic" } }, 4242, 1),
    ).toBeNull();
    const twice = { ...CUP, results: [CUP.results[0]!, CUP.results[0]!] };
    expect(readH2hStandings(twice, 4242, 1)).toBeNull();
  });

  it("gives rows in the classic shape, the points for as the total and no week stated", () => {
    expect(tableRows(CUP)[1]).toEqual({
      entry: 7002,
      entry_name: "Cup Team 2",
      player_name: "Cup Manager 2",
      rank: 2,
      rank_sort: 2,
      last_rank: 3,
      total: 593,
      event_total: null,
    });
  });
});

describe("a week's pairings", () => {
  it("read when they are the league's, the week's and the page's; the average has no entry", () => {
    expect(readH2hMatches(WEEK, 4242, 9, 1)).toEqual(WEEK);
    expect(readH2hMatches(WEEK, 4242, 8, 1)).toBeNull();
    expect(readH2hMatches(WEEK, 4242, 9, 2)).toBeNull();
    const damaged = {
      ...WEEK,
      results: [{ ...WEEK.results[0]!, entry_1: { ...WEEK.results[0]!.entry_1, points: "60" } }],
    };
    expect(readH2hMatches(damaged, 4242, 9, 1)).toBeNull();
  });
});
