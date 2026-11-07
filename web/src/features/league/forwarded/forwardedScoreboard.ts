/**
 * The scoreboard and the member histories of a league the site does not publish, built on
 * the device from FPL's own documents: each member's season (`fpl_entry_season_v1`), the
 * game's events (`fpl_events_v1`) and the site's calendar. The weekly run writes the same
 * documents for a listed league from its capture; here every figure is what FPL states for
 * the members the page has read, and nothing is projected, settled or compared with the
 * system's own squad, so those rows stay null.
 */

import type { FixturesPayload } from "../../fixtures/types";
import type { DevicePlanDocument } from "../device/types";
import type { FplEntrySeason, FplEvents } from "../forwarder/documents";
import type { SuggestionHistory } from "../history/historyData";
import type {
  LeagueViewEnvelope,
  Scoreboard,
  ScoreboardGameweek,
  ScoreboardMember,
} from "../types";

export interface ForwardedScoreboardInputs {
  leagueId: number;
  table: LeagueViewEnvelope<DevicePlanDocument>;
  /** The members the page has read, with the season of each the forwarder answered. */
  members: readonly { entry: number }[];
  seasons: ReadonlyMap<number, FplEntrySeason>;
  events: FplEvents;
  fixtures: FixturesPayload | null;
}

function mean(values: readonly number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function deadlineOf(fixtures: FixturesPayload | null, gameweek: number): string | null {
  return fixtures?.gameweeks.find((week) => week.gameweek === gameweek)?.deadline_utc ?? null;
}

/**
 * The scoreboard: one row per gameweek the game lists up to the latest any member has
 * played, each with the members' gross, hit, net and running total from their seasons, the
 * members' mean net, and the game's own average and highest score from the events. A
 * member whose season the forwarder did not answer is left out of every week and counted in
 * none. The system's own row and the Top 100 row are null: nothing of either exists for
 * such a league.
 */
export function forwardedScoreboard({
  leagueId,
  table,
  members,
  seasons,
  events,
  fixtures,
}: ForwardedScoreboardInputs): LeagueViewEnvelope<Scoreboard> {
  const played = new Set<number>();
  for (const season of seasons.values()) for (const week of season.weeks) played.add(week.event);
  const latest = Math.max(0, ...played);
  const gameweeks: ScoreboardGameweek[] = [];
  for (const event of events.events) {
    if (event.id > latest) continue;
    const deadline = deadlineOf(fixtures, event.id);
    if (deadline === null) continue;
    const rows: ScoreboardMember[] = [];
    for (const member of members) {
      const week = seasons.get(member.entry)?.weeks.find((row) => row.event === event.id);
      if (week === undefined) continue;
      rows.push({
        entry_id: member.entry,
        points: week.points,
        hit_cost: week.event_transfers_cost,
        net: week.points - week.event_transfers_cost,
        total_points: week.total_points,
      });
    }
    gameweeks.push({
      gameweek: event.id,
      deadline_utc: deadline,
      finished: event.finished,
      data_checked: event.data_checked,
      average_entry_score: event.finished ? event.average_entry_score : null,
      highest_score: event.highest_score,
      ours: null,
      top100: null,
      members: rows,
      members_mean_net: mean(
        rows.map((row) => row.net).filter((net): net is number => net !== null),
      ),
      members_counted: rows.length,
    });
  }
  const settled = gameweeks.filter((week) => week.finished && week.data_checked);
  const through = settled.at(-1) ?? null;
  const totals = through?.members.map((row) => row.total_points) ?? [];
  return {
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: events.source_time,
    source_kind: "live",
    payload: {
      season: table.payload.season,
      league_id: leagueId,
      source_snapshot_id: table.payload.source_snapshot_id,
      captured_at_utc: table.generated_at_utc,
      cohort_snapshot_id: null,
      cohort_picks_snapshot_id: null,
      gameweeks,
      cumulative: {
        through_gameweek: through?.gameweek ?? null,
        gameweeks: settled.map((week) => week.gameweek),
        members_mean_total_points: mean(totals),
        members_counted: totals.length,
        average_entry_score:
          through === null
            ? null
            : settled.reduce((sum, week) => sum + (week.average_entry_score ?? 0), 0),
      },
    },
  };
}

/**
 * A member's history as the history page reads it, for a league nothing was recorded for:
 * one row per played week, each saying no record was made before its deadline. What the
 * member asked the service for is the requested history's to say, and a week it names
 * replaces the row here (`loadSuggestionHistory`).
 */
export function forwardedHistory({
  leagueId,
  table,
  season,
  fixtures,
}: {
  leagueId: number;
  table: LeagueViewEnvelope<DevicePlanDocument>;
  season: FplEntrySeason;
  fixtures: FixturesPayload | null;
}): SuggestionHistory {
  return {
    contract_version: "weekly_suggestion_history_v1",
    generated_at_utc: season.source_time,
    payload: {
      league_id: leagueId,
      entry_id: season.entry_id,
      season: table.payload.season,
      as_of_snapshot_id: table.payload.source_snapshot_id,
      weeks: season.weeks.map((week) => ({
        gameweek: week.event,
        status: "unavailable" as const,
        reason: "no_pre_deadline_record",
        deadline_utc: deadlineOf(fixtures, week.event),
        advice_snapshot_id: null,
        advice_captured_at_utc: null,
        advice_generated_at_utc: null,
        advice_sha256: null,
        outcome_snapshot_id: null,
        outcome_captured_at_utc: null,
        expected_own_points: null,
        suggested: null,
        actual: null,
        actual_reason: null,
        net_difference: null,
        players: [],
      })),
    },
  };
}
