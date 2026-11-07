/**
 * The arithmetic behind VS SQUADOPT's week: which recorded plan is the one the history scored,
 * what each plan moved, and where the week's difference came from.
 */

import type { RecordedPlan, WeekReview } from "../history/historyData";

/** The plain one-week plan: the one whose squad the history scored. */
export function plainPlan(week: WeekReview): RecordedPlan | null {
  return (
    week.recorded_plans?.find(
      (row) =>
        row.strategy === "saf-puan" &&
        row.rival_entry_id === null &&
        row.top100_weight === undefined &&
        row.managers_word === undefined &&
        row.chip === null,
    ) ?? null
  );
}

/** Every other plan the week recorded, in the order recorded. */
export function otherPlans(week: WeekReview): RecordedPlan[] {
  const plain = plainPlan(week);
  return (week.recorded_plans ?? []).filter((row) => row !== plain);
}

/** A plan's moves with both names stated. */
export function movesOf(plan: RecordedPlan | null): { out: string; in: string }[] {
  return (plan?.moves ?? [])
    .filter((move) => move.player_out !== null && move.player_in !== null)
    .map((move) => ({ out: move.player_out!, in: move.player_in! }));
}

export interface Breakdown {
  captain: number;
  transfers: number;
  hits: number;
  lineup: number;
}

/**
 * Where the week's difference (SquadOpt's net less the member's) came from, in points that
 * favour SquadOpt when positive: the captain's bonus, the players brought in, the hits paid,
 * and what remains, which is the rest of the squad and the bench. Null without the member's
 * details, since the first three cannot then be told apart.
 */
export function breakdown(week: WeekReview): Breakdown | null {
  const detail = week.actual?.details ?? null;
  const suggested = week.suggested;
  if (detail === null || suggested === null || week.net_difference === null) return null;
  const captain =
    suggested.captain_bonus_points - (detail.captain.counted_points - detail.captain.points);
  const byName = new Map(week.players.map((player) => [player.name, player]));
  const planIns = movesOf(plainPlan(week))
    .map((move) => byName.get(move.in)?.realized_points)
    .filter((value): value is number => value !== undefined);
  const transfers =
    planIns.reduce((sum, value) => sum + value, 0) -
    detail.transfers.reduce((sum, move) => sum + move.player_in.points, 0);
  const hits = (week.actual?.transfer_hit_points ?? 0) - suggested.transfer_hit_points;
  const lineup = week.net_difference - captain - transfers - hits;
  return { captain, transfers, hits, lineup };
}
