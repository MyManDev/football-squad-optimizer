import { describe, expect, it } from "vitest";

import type { LiveEvent } from "./liveEvents";
import {
  liveMoments,
  MAX_BIG_MOMENTS,
  SEASON_EVENT_POINTS,
  type MomentContext,
} from "./liveMoments";
import type { Position } from "./weekLive";

const PLAYERS: [number, Position][] = [
  [1, "GK"],
  [2, "DEF"],
  [3, "MID"],
  [4, "FWD"],
  [5, "MID"],
  [6, "FWD"],
  [12, "FWD"],
];

const context = (overrides: Partial<MomentContext> = {}): MomentContext => ({
  read: 7,
  season: "2026-27",
  counted: [1, 2, 3, 4, 5, 6],
  captain: 4,
  tripleCaptain: false,
  players: new Map(
    PLAYERS.map(([id, position]) => [id, { name: `Player ${id}`, team: `Club ${id}`, position }]),
  ),
  ...overrides,
});

const goal = (elementId: number, count = 1): LiveEvent => ({ kind: "goal", elementId, count });

describe("liveMoments", () => {
  it("gives a goal the season's points for the scorer's position", () => {
    const points = liveMoments([goal(1), goal(2), goal(3)], context({ captain: null })).map(
      ({ elementId, points: value }) => [elementId, value],
    );
    expect(points).toEqual([
      [1, 10],
      [2, 6],
      [3, 5],
    ]);
  });

  it("doubles the captain's goal and triples it under the triple captain", () => {
    const [doubled] = liveMoments([goal(4)], context());
    expect(doubled).toMatchObject({ size: "big", base: 4, multiplier: 2, points: 8 });
    const [tripled] = liveMoments([goal(4, 2)], context({ tripleCaptain: true }));
    expect(tripled).toMatchObject({ base: 8, multiplier: 3, points: 24, count: 2 });
  });

  it("makes an assist big beside the goals, a card small without points, and a reserve's goal small", () => {
    const moments = liveMoments(
      [
        { kind: "card", elementId: 5, count: 1 },
        { kind: "assist", elementId: 4, count: 1 },
        goal(12),
      ],
      context(),
    );
    expect(moments.map(({ kind, size, points }) => [kind, size, points])).toEqual([
      ["assist", "big", 6],
      ["goal", "small", 0],
      ["card", "small", null],
    ]);
    expect(moments[1]).toMatchObject({ multiplier: 0, base: 4 });
  });

  it("plays goals before assists, whatever the points", () => {
    const moments = liveMoments([{ kind: "assist", elementId: 4, count: 2 }, goal(6)], context());
    expect(moments.map(({ kind, size, points }) => [kind, size, points])).toEqual([
      ["goal", "big", 4],
      ["assist", "big", 12],
    ]);
  });

  it("plays the biggest goals first, at most three big moments with the assists", () => {
    const moments = liveMoments([goal(3), goal(6), goal(1), goal(2), goal(4)], context());
    expect(moments.filter(({ size }) => size === "big")).toHaveLength(MAX_BIG_MOMENTS);
    expect(moments.map(({ elementId, size }) => [elementId, size])).toEqual([
      [1, "big"],
      [4, "big"],
      [2, "big"],
      [3, "small"],
      [6, "small"],
    ]);
  });

  it("knows no points in a season it does not list, and skips a pick it cannot name", () => {
    expect(SEASON_EVENT_POINTS["2027-28"]).toBeUndefined();
    const [moment, ...rest] = liveMoments([goal(3), goal(77)], context({ season: "2027-28" }));
    expect(moment).toMatchObject({ size: "big", base: null, points: null });
    expect(rest).toEqual([]);
  });

  it("keys each moment by its read, kind and player", () => {
    expect(liveMoments([goal(3)], context())[0]!.key).toBe("7:goal:3");
  });
});
