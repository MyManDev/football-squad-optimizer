import { describe, expect, it } from "vitest";

import { follower, gapToLeader, leaderTotal, netWeekPoints } from "./standing";

const row = (rank: number, total_points: number | null) => ({ rank, total_points });

describe("the league table's derived columns", () => {
  it("nets the week only when both halves are known", () => {
    expect(netWeekPoints({ gameweek_points: 58, transfer_cost: 8 })).toBe(50);
    expect(netWeekPoints({ gameweek_points: 58, transfer_cost: null })).toBeNull();
    expect(netWeekPoints({ gameweek_points: null, transfer_cost: 0 })).toBeNull();
  });

  it("measures every gap from the member ranked first", () => {
    const rows = [row(1, 371), row(2, 366), row(3, 360)];
    const lead = leaderTotal(rows);
    expect(lead).toBe(371);
    expect(rows.map((item) => gapToLeader(lead, item))).toEqual([0, 5, 11]);
  });

  it("has no leader when the first total is unknown or not the highest", () => {
    expect(leaderTotal([row(1, null), row(2, 366)])).toBeNull();
    expect(leaderTotal([row(1, 300), row(2, 366)])).toBeNull();
    expect(leaderTotal([])).toBeNull();
    expect(gapToLeader(null, row(2, 366))).toBeNull();
  });

  it("leaves an unknown total without a gap, never a gap of the whole lead", () => {
    const lead = leaderTotal([row(1, 371), row(2, null)]);
    expect(gapToLeader(lead, row(2, null))).toBeNull();
  });

  it("finds the member right behind, and how far", () => {
    const rows = [row(1, 371), row(2, 366), row(3, 366)];
    expect(follower(rows, rows[0]!)).toEqual({ member: rows[1], behind: 5 });
    expect(follower(rows, rows[1]!)).toEqual({ member: rows[2], behind: 0 });
    expect(follower(rows, rows[2]!)).toBeNull();
    const unknown = [row(1, 371), row(2, null)];
    expect(follower(unknown, unknown[0]!)).toEqual({ member: unknown[1], behind: null });
    // A next row with more points is not "behind": no distance rather than a negative one.
    const unordered = [row(1, 300), row(2, 310)];
    expect(follower(unordered, unordered[0]!)).toEqual({ member: unordered[1], behind: null });
  });
});
