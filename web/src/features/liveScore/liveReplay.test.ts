import { describe, expect, it } from "vitest";

import { MOTION_MS } from "../../design/motion";
import { MOMENT_TIMING } from "./goalMomentTiming";
import { REPLAY_START_MS, REPLAY_STEP_MS, replayEvents } from "./liveReplay";

const row = (element_id: number, fixture_id: number, goals: number, assists: number) => ({
  element_id,
  fixture_id,
  minutes: 90,
  goals,
  assists,
});

describe("replayEvents", () => {
  it("gives each goal and assist of the member's picks a step of its own", () => {
    const events = replayEvents(
      {
        in_play_fixtures: [],
        appearances: [row(3, 20, 0, 1), row(1, 20, 2, 0), row(99, 10, 3, 3), row(2, 10, 1, 1)],
      },
      [1, 2, 3],
    );
    expect(events).toEqual([
      { kind: "goal", elementId: 2, count: 1 },
      { kind: "assist", elementId: 2, count: 1 },
      { kind: "goal", elementId: 1, count: 1 },
      { kind: "goal", elementId: 1, count: 1 },
      { kind: "assist", elementId: 3, count: 1 },
    ]);
  });

  it("gives nothing for a week without goals or assists", () => {
    expect(replayEvents({ in_play_fixtures: [], appearances: [row(1, 10, 0, 0)] }, [1])).toEqual(
      [],
    );
  });

  it("leaves each step room for a board's whole moment, or a still line", () => {
    expect(REPLAY_STEP_MS % MOTION_MS.data).toBe(0);
    expect(REPLAY_START_MS % MOTION_MS.data).toBe(0);
    const board = MOMENT_TIMING.rise + MOMENT_TIMING.holdGoal + MOTION_MS.data + MOMENT_TIMING.fall;
    expect(REPLAY_STEP_MS).toBeGreaterThan(board);
    expect(REPLAY_STEP_MS).toBeGreaterThan(MOMENT_TIMING.still);
  });
});
