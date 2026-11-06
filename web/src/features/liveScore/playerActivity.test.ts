import { describe, expect, it } from "vitest";

import examples from "../../../../docs/contracts/week_activity_v1.examples.json";
import { advanceActivity, playerActivities } from "./playerActivity";
import { weekActivity } from "./weekActivity";

const read = () => weekActivity(structuredClone(examples.in_progress));
const players = () => playerActivities(read().activity!, [1, 2, 3]);
const at = (minute: number) => `2026-10-31T16:${String(minute).padStart(2, "0")}:00Z`;

describe("live activity evidence", () => {
  it("reads every committed example", () => {
    for (const example of Object.values(examples)) expect(weekActivity(example)).toEqual(example);
  });
  it("shows only the member's picks and ties participation to the same live fixture", () => {
    const result = players();
    expect(
      result.map((row) => [row.elementId, row.matchInProgress, row.goals, row.assists]),
    ).toEqual([
      [1, true, 1, 1],
      [2, true, 0, 0],
      [3, false, 0, 0],
    ]);
    const document = read();
    document.activity!.appearances[0]!.minutes = 0;
    const held = playerActivities(document.activity!, [1]);
    expect(held[0]!.matchInProgress).toBe(false);
    expect(held[0]!.assists).toBe(1);
  });
  it.each(["unknown", "duplicate", "finished", "minutes", "negative", "extra"])(
    "refuses %s activity evidence",
    (kind) => {
      const document = read();
      const activity = document.activity!;
      if (kind === "unknown") activity.appearances[0]!.element_id = 999;
      if (kind === "duplicate") activity.appearances.push(activity.appearances[0]!);
      if (kind === "finished") activity.in_play_fixtures.push(92);
      if (kind === "minutes") activity.appearances[0]!.minutes += 1;
      if (kind === "negative") activity.appearances[0]!.goals = -1;
      if (kind === "extra") Object.assign(activity.appearances[0]!, { raw: "no" });
      expect(() => weekActivity(document)).toThrow("invalid_activity");
    },
  );
});

describe("event highlights", () => {
  it("does not animate historical events on first read, only a newer realized increase", () => {
    const current = players();
    const baseline = advanceActivity(null, "entry:9", at(0), current);
    expect(baseline.highlights.size).toBe(0);
    current[0]!.appearances[0]!.goals = 2;
    const next = advanceActivity(baseline, "entry:9", at(1), current);
    expect([...next.highlights]).toEqual([[1, 1]]);
    expect(advanceActivity(next, "entry:9", at(1), current)).toBe(next);
    expect(advanceActivity(next, "entry:9", at(0), current)).toBe(next);
    expect([...advanceActivity(next, "entry:9", at(2), current).highlights]).toEqual([[1, 1]]);
  });
  it("does not replay corrected events and independently tracks the second match", () => {
    const current = players();
    let history = advanceActivity(null, "entry:9", at(0), current);
    current[0]!.appearances[0]!.goals = 0;
    history = advanceActivity(history, "entry:9", at(1), current);
    current[0]!.appearances[0]!.goals = 1;
    history = advanceActivity(history, "entry:9", at(2), current);
    expect(history.highlights.size).toBe(0);
    current[0]!.appearances[1]!.goals = 1;
    history = advanceActivity(history, "entry:9", at(3), current);
    expect([...history.highlights]).toEqual([[1, 1]]);
    expect(advanceActivity(history, "other-entry:9", at(3), current).highlights.size).toBe(0);
    expect(advanceActivity(history, "entry:10", at(3), current).highlights.size).toBe(0);
  });
});
