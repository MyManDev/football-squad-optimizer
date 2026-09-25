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

type Ranked = Pick<EntryView, "rank" | "total_points">;

const known = (value: number | null): value is number =>
  typeof value === "number" && Number.isFinite(value);

/**
 * The leader's season total, the figure every row's gap is measured from: the total of the
 * member ranked first. With that total unknown, or with another member's known total above
 * it (a table not ordered by these totals), there is no leader to measure from, and every
 * gap is unknown rather than guessed.
 */
export function leaderTotal(rows: readonly Ranked[]): number | null {
  const ranked = rows.filter((row) => Number.isSafeInteger(row.rank) && row.rank > 0);
  if (ranked.length === 0) return null;
  const top = Math.min(...ranked.map((row) => row.rank));
  const totals = ranked.filter((row) => row.rank === top).map((row) => row.total_points);
  if (!totals.every(known)) return null;
  const lead = Math.max(...totals);
  return rows.some((row) => known(row.total_points) && row.total_points > lead) ? null : lead;
}

/** Points behind the leader: 0 for the leader, null when either total is unknown. */
export function gapToLeader(lead: number | null, row: Ranked): number | null {
  return lead === null || !known(row.total_points) ? null : lead - row.total_points;
}

/**
 * The member right behind `viewer` in the published order, and how many points behind:
 * null for the last row, and `behind` null when either total is unknown or when the next
 * row has more points (a table not ordered by these totals is not a distance to state).
 */
export function follower<T extends Ranked>(
  rows: readonly T[],
  viewer: T,
): { member: T; behind: number | null } | null {
  const index = rows.indexOf(viewer);
  const next = index < 0 ? undefined : rows[index + 1];
  if (!next) return null;
  const behind =
    known(viewer.total_points) && known(next.total_points)
      ? viewer.total_points - next.total_points
      : null;
  return { member: next, behind: behind !== null && behind >= 0 ? behind : null };
}
