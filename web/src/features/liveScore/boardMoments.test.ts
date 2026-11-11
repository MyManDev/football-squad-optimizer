import { describe, expect, it } from "vitest";

import { newSubstitutions, shownOnBoard } from "./boardMoments";
import type { LiveMoment } from "./liveMoments";

const goal = (multiplier: LiveMoment["multiplier"]): LiveMoment => ({
  key: "1:goal:9",
  kind: "goal",
  size: multiplier === 0 ? "small" : "big",
  elementId: 9,
  name: "Cherki",
  team: "Man City",
  position: "MID",
  count: 1,
  multiplier,
  base: 5,
  points: multiplier === 0 ? null : 5 * multiplier,
});

describe("shownOnBoard", () => {
  it("shows what brings the member points, and a substitution", () => {
    expect(shownOnBoard(goal(1))).toBe(true);
    expect(shownOnBoard(goal(2))).toBe(true);
    // A reserve the scorer does not count (no bench boost) raises nothing.
    expect(shownOnBoard(goal(0))).toBe(false);
    expect(shownOnBoard({ key: "s", kind: "substitution", size: "big", out: "A", in: "B" })).toBe(
      true,
    );
  });
});

describe("newSubstitutions", () => {
  it("takes the first read's pairs as a starting point", () => {
    const first = newSubstitutions(null, [[1, 12]]);
    expect(first.fresh).toEqual([]);
    expect([...first.seen]).toEqual(["1:12"]);
  });

  it("names the pairs a newer read adds, once", () => {
    const first = newSubstitutions(null, []);
    const second = newSubstitutions(first.seen, [
      [4, 13],
      [7, 14],
    ]);
    expect(second.fresh).toEqual([
      [4, 13],
      [7, 14],
    ]);
    expect(newSubstitutions(second.seen, [[4, 13]]).fresh).toEqual([]);
  });
});
