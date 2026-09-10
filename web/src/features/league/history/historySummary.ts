import type { WeekReview } from "./historyData";

/** Aggregate already scored weeks; both sides use exactly the same comparable weeks. */
export function summarizeHistory(weeks: readonly WeekReview[]) {
  let suggested = 0;
  let actual = 0;
  let difference = 0;
  let compared = 0;
  const rows = [...weeks]
    .sort((a, b) => a.gameweek - b.gameweek)
    .map((week) => {
      const comparable =
        week.status === "available" &&
        week.suggested !== null &&
        week.actual !== null &&
        week.net_difference !== null;
      if (comparable) {
        suggested += week.suggested!.net_points;
        actual += week.actual!.net_points;
        difference += week.net_difference!;
        compared += 1;
      }
      return { week, cumulative: comparable ? difference : null };
    });
  return {
    rows,
    compared,
    suggested: compared ? suggested : null,
    actual: compared ? actual : null,
    difference: compared ? difference : null,
  };
}
