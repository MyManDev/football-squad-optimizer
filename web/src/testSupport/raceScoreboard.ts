/**
 * Small scoreboards for the league race's tests (#1135): human members by id, and weeks
 * whose rows carry only the total each member stands on.
 */
import type { EntryView, Scoreboard, ScoreboardGameweek } from "../features/league/types";

export function raceMember(entryId: number): EntryView {
  return {
    entry_id: entryId,
    member_kind: "human",
    manager_name: `M${entryId}`,
    team_name: `T${entryId}`,
    rank: 1,
    gameweek_points: null,
    transfer_cost: null,
    total_points: null,
    movement: "unknown",
    movement_places: null,
    data_quality: "complete",
  };
}

export const RACE_SYSTEM: EntryView = { ...raceMember(1), member_kind: "system", entry_id: null };

export function raceWeek(
  gameweek: number,
  totals: Record<number, number>,
  settled = true,
): ScoreboardGameweek {
  return {
    gameweek,
    deadline_utc: "2026-08-21T17:30:00Z",
    finished: settled,
    data_checked: settled,
    average_entry_score: null,
    highest_score: null,
    ours: null,
    top100: null,
    members: Object.entries(totals).map(([entryId, total]) => ({
      entry_id: Number(entryId),
      points: 0,
      hit_cost: 0,
      net: 0,
      total_points: total,
    })),
    members_mean_net: null,
    members_counted: Object.keys(totals).length,
  };
}

export function raceScoreboard(weeks: ScoreboardGameweek[]): Scoreboard {
  return {
    season: "2026-27",
    league_id: 1,
    source_snapshot_id: "s",
    captured_at_utc: "2026-10-01T00:00:00Z",
    cohort_snapshot_id: null,
    cohort_picks_snapshot_id: null,
    registered_members: 3,
    histories_held: 3,
    gameweeks: weeks,
    cumulative: {
      through_gameweek: null,
      gameweeks: [],
      ours_net: null,
      ours_gameweeks: [],
      ours_basis: null,
    } as unknown as Scoreboard["cumulative"],
  };
}
