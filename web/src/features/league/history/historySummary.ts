import { availableWeek, weekState } from "../../../lib/weekState";
import type { WeekReview } from "./historyData";

/** `available` is the history contract's recorded finished-and-checked result. */
function historyWeekState(weeks: readonly WeekReview[]) {
  return weekState({
    treeGameweek: null,
    events: weeks.map((week) => ({
      gameweek: week.gameweek,
      finished: week.status === "available",
      data_checked: week.status === "available",
      deadline_utc: week.deadline_utc,
    })),
    fixtures: null,
    now: Number.POSITIVE_INFINITY,
  });
}

export function settledHistoryWeeks(weeks: readonly WeekReview[]): number[] {
  return historyWeekState(weeks).checkedWeeks;
}

/** Aggregate already scored weeks; both sides use exactly the same comparable weeks. */
export function summarizeHistory(weeks: readonly WeekReview[]) {
  const state = historyWeekState(weeks);
  const checked = state.checkedWeeks;
  const available = weeks
    .filter(
      (week) => week.suggested !== null && week.actual !== null && week.net_difference !== null,
    )
    .map((week) => week.gameweek);
  const current = checked.filter((gameweek) => available.includes(gameweek)).at(-1) ?? null;
  const throughGameweek = availableWeek(state.weeks.history, current, available);
  let suggested = 0;
  let actual = 0;
  let difference = 0;
  let compared = 0;
  const rows = [...weeks]
    .sort((a, b) => a.gameweek - b.gameweek)
    .map((week) => {
      const scored = checked.includes(week.gameweek);
      const comparable =
        scored &&
        throughGameweek !== null &&
        week.gameweek <= throughGameweek &&
        week.suggested !== null &&
        week.actual !== null &&
        week.net_difference !== null;
      if (comparable) {
        suggested += week.suggested!.net_points;
        actual += week.actual!.net_points;
        difference += week.net_difference!;
        compared += 1;
      }
      return { week, scored, cumulative: comparable ? difference : null };
    });
  return {
    rows,
    throughGameweek,
    suggested: compared ? suggested : null,
    actual: compared ? actual : null,
    difference: compared ? difference : null,
  };
}
