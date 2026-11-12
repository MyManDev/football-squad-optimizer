/** The match day the motion tests replay: each read scores as its story says. */

import { describe, expect, it } from "vitest";

import { liveBoard, type LiveBoard } from "../features/league/live/liveBoard";
import { liveBeats, type BeatName } from "./liveBeats";

const boards = new Map<BeatName, LiveBoard>(
  liveBeats().map((beat) => [beat.name, liveBoard(beat.input)!]),
);
const board = (name: BeatName) => boards.get(name)!;
const ids = (name: BeatName, group: keyof LiveBoard["groups"]) =>
  board(name).groups[group].map((row) => row.elementId);
const row = (name: BeatName, id: number) => board(name).rows.find((r) => r.elementId === id)!;

describe("the replayed match day", () => {
  it("reads eight times, each newer than the last", () => {
    const times = liveBeats().map((beat) => Date.parse(beat.at));
    expect(times).toHaveLength(8);
    times.slice(1).forEach((time, index) => expect(time).toBeGreaterThan(times[index]!));
  });

  it("starts before the kickoffs and puts the 12:30 match's six under way", () => {
    expect(ids("before", "playing")).toEqual([]);
    expect(board("before").net).toBe(0);
    expect(ids("kickoff", "playing")).toEqual([10, 1, 2, 3, 6, 7]);
    expect(board("kickoff").net).toBe(7);
  });

  it("brings the captain's goal and the vice's assist, then a card", () => {
    expect(row("goal", 10)).toMatchObject({ goals: 1, state: "up", multiplier: 2 });
    expect(row("goal", 7)).toMatchObject({ assists: 1, state: "up" });
    expect(board("goal").net).toBe(18);
    expect(row("card", 2)).toMatchObject({ card: true, state: "down" });
    expect(board("card").net).toBe(17);
  });

  it("ends the first match at its window as the second starts, then adds its bonus", () => {
    expect(ids("over", "finished")).toEqual([10, 1, 2, 3, 6, 7]);
    expect(ids("over", "playing")).toEqual([4, 5, 8, 11]);
    expect(board("over").final).toBe(false);
    expect(ids("bonus", "playing")).toEqual([4, 5, 8, 11]);
    const changed = board("bonus").rows.filter(
      (r) => r.counted && r.points !== row("over", r.elementId).points,
    );
    expect(changed.length).toBeGreaterThan(6);
  });

  it("finishes the week with the forward who never played giving way to the first reserve", () => {
    expect(ids("second", "finished")).toEqual(expect.arrayContaining([4, 5, 8, 11]));
    expect(board("final").final).toBe(true);
    expect(row("final", 11)).toMatchObject({ autosub: "out", counted: false });
    expect(row("final", 13)).toMatchObject({ autosub: "in", counted: true });
  });
});
