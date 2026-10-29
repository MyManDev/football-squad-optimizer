/**
 * What the latest-week card may say, decided from the documents alone: the latest finished
 * week in whatever order the scoreboard lists it, the rank movement only as a count or as
 * unchanged, and the suggestion's score only from the member's own settled week.
 */

import { describe, expect, it } from "vitest";

import fixture from "../../../fixtures/weeklySuggestionHistory.json";
import { mockEntrySquadEnvelopes } from "../../../fixtures/league";
import type { SuggestionHistory } from "../history/historyData";
import type { EntrySquad, RankMovement, Scoreboard, ScoreboardGameweek } from "../types";
import { lastWeekResult } from "./lastWeekResult";

const ENTRY = 35249001;
const SQUAD = mockEntrySquadEnvelopes[ENTRY]!.payload;

function week(gameweek: number, patch: Partial<ScoreboardGameweek> = {}): ScoreboardGameweek {
  return {
    gameweek,
    deadline_utc: "2026-08-15T17:30:00Z",
    finished: true,
    data_checked: true,
    average_entry_score: 50,
    highest_score: 100,
    ours: null,
    top100: null,
    members: [
      { entry_id: ENTRY, points: 60 + gameweek, hit_cost: 0, net: 60 + gameweek, total_points: 0 },
    ],
    members_mean_net: 55,
    members_counted: 10,
    ...patch,
  };
}

function board(weeks: ScoreboardGameweek[]): Scoreboard {
  return {
    season: SQUAD.season,
    league_id: SQUAD.league_id,
    source_snapshot_id: "fpl-live-test",
    captured_at_utc: "2026-08-22T04:00:00Z",
    cohort_snapshot_id: null,
    cohort_picks_snapshot_id: null,
    registered_members: 10,
    histories_held: 10,
    gameweeks: weeks,
    cumulative: {
      through_gameweek: null,
      gameweeks: [],
      ours_net: null,
      ours_gameweeks: [],
      ours_basis: null,
      ours_excluded_gameweeks: [],
      members_mean_total_points: null,
      members_gameweeks: [],
      members_counted: 0,
      average_entry_score: null,
    },
  };
}

function standing(movement: RankMovement, places: number | null, scored = 1): EntrySquad {
  return {
    ...SQUAD,
    scored_gameweek: scored,
    entry: { ...SQUAD.entry, movement, movement_places: places },
  };
}

function history(gameweek: number, status: "available" | "unsettled" = "available") {
  const value = structuredClone(fixture) as SuggestionHistory;
  value.payload.entry_id = ENTRY;
  // The fixture's suggestion: 24 gross less a 4-point hit, 20 net.
  Object.assign(value.payload.weeks[0]!, { gameweek, status });
  return value;
}

describe("the latest finished week", () => {
  it("is the highest finished gameweek, whatever order the scoreboard lists them in", () => {
    const result = lastWeekResult(
      standing("up", 1, 3),
      board([week(3), week(1), week(4, { finished: false }), week(2)]),
      null,
    );
    expect(result).toMatchObject({ gameweek: 3, net: 63, provisional: false });
  });

  it("is said provisional when it is finished and not checked", () => {
    expect(lastWeekResult(SQUAD, board([week(1, { data_checked: false })]), null)).toMatchObject({
      gameweek: 1,
      provisional: true,
    });
  });

  it.each<[RankMovement, number | null, number, unknown]>([
    ["up", 2, 1, { movement: "up", places: 2 }],
    ["down", 1, 1, { movement: "down", places: 1 }],
    ["same", 0, 1, { movement: "same", places: 0 }],
    // Not a count of places, or not this week's standing: no movement is said.
    ["up", null, 1, null],
    ["same", null, 1, null],
    ["new", null, 1, null],
    ["unknown", null, 1, null],
    ["up", 2, 0, null],
  ])("says the movement %s %s (scored week %s) as %j", (movement, places, scored, expected) => {
    const result = lastWeekResult(standing(movement, places, scored), board([week(1)]), null);
    expect(result?.movement).toEqual(expected);
  });

  it("takes the suggestion's net only from the member's own settled week", () => {
    const at = (value: SuggestionHistory | null) =>
      lastWeekResult(SQUAD, board([week(1)]), value)?.suggested;
    expect(at(history(1))).toBe(20);
    expect(at(history(2))).toBeNull();
    // Not settled is not a score, even with a figure left in the row.
    expect(at(history(1, "unsettled"))).toBeNull();
    const unscored = history(1);
    unscored.payload.weeks[0]!.suggested = null;
    expect(at(unscored)).toBeNull();
    const otherMember = history(1);
    otherMember.payload.entry_id = 35249002;
    expect(at(otherMember)).toBeNull();
    const otherSeason = history(1);
    otherSeason.payload.season = "2025-26";
    expect(at(otherSeason)).toBeNull();
    expect(at(null)).toBeNull();
  });

  it("states no mean that counts no member", () => {
    const result = lastWeekResult(SQUAD, board([week(1, { members_counted: 0 })]), null);
    expect(result?.leagueMean).toBeNull();
    expect(result?.gameAverage).toBe(50);
  });
});
