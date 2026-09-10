import fixture from "./weeklySuggestionHistory.json" with { type: "json" };
import type { SuggestionHistory, WeekReview } from "../features/league/history/historyData";

/** Synthetic multi-week evidence for tests and the explicitly labelled local mock preview. */
export function mockSuggestionOverview(): SuggestionHistory {
  const history = structuredClone(fixture) as SuggestionHistory;
  const differences = [-2, 6, 4, 4, -3, 8, 0, -5, 9, 2];
  history.payload.weeks = differences.map((difference, index) => {
    const week = structuredClone(history.payload.weeks[0]);
    week.gameweek = index + 4;
    week.advice_snapshot_id = `mock-advice-gw${week.gameweek}`;
    week.outcome_snapshot_id = `mock-result-gw${week.gameweek}`;
    for (const field of [
      "deadline_utc",
      "advice_captured_at_utc",
      "advice_generated_at_utc",
      "outcome_captured_at_utc",
    ] as const) {
      week[field] = new Date(Date.parse(week[field]!) + index * 7 * 86_400_000).toISOString();
    }
    week.players.forEach((player) => {
      player.realized_points = 2 + index;
      player.counted_points = player.realized_points * player.multiplier;
      player.forecast_error = player.realized_points - player.expected_points!;
    });
    week.suggested!.gross_points = 24 + 12 * index;
    week.suggested!.net_points = week.suggested!.gross_points - 4;
    week.suggested!.captain_bonus_points = 2 + index;
    week.actual!.net_points = week.suggested!.net_points - difference;
    week.actual!.gross_points = week.actual!.net_points + week.actual!.transfer_hit_points;
    week.net_difference = difference;
    return week;
  });
  // GW12 has a scored suggestion, but no captured member result; exclude it from totals.
  Object.assign(history.payload.weeks[8], {
    actual: null,
    actual_reason: "actual_score_missing",
    net_difference: null,
  });
  const pending: WeekReview = {
    ...structuredClone(history.payload.weeks[9]),
    gameweek: 14,
    status: "unsettled",
    reason: "not_settled",
    suggested: null,
    actual: null,
    actual_reason: null,
    net_difference: null,
    players: [],
    outcome_snapshot_id: null,
    outcome_captured_at_utc: null,
  };
  history.payload.weeks.push(pending);
  for (const field of [
    "deadline_utc",
    "advice_captured_at_utc",
    "advice_generated_at_utc",
  ] as const) {
    pending[field] = new Date(Date.parse(pending[field]!) + 7 * 86_400_000).toISOString();
  }
  pending.advice_snapshot_id = "mock-advice-gw14";
  history.generated_at_utc = "2026-11-19T09:00:00Z";
  return history;
}
