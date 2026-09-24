import type { EntryView } from "./types";

type Standing = Pick<EntryView, "gameweek_points" | "transfer_cost">;

/**
 * A member's week on the one basis the league table uses: the score after the transfer
 * hits taken that week.
 *
 * That is the number the league total actually advances by (the source's own arithmetic
 * has `total_points` move by `points` minus `event_transfers_cost`), so it is the only
 * basis on which our row and a member's row are the same measurement.
 *
 * Both halves must be known. A missing hit is not a hit of zero: the producer publishes
 * null when nothing proves one, and a row like that shows no week rather than its gross
 * score under a heading that says net.
 */
export function netWeekPoints(member: Standing): number | null {
  const gross = member.gameweek_points;
  const cost = member.transfer_cost;
  if (typeof gross !== "number" || typeof cost !== "number") return null;
  return gross - cost;
}
