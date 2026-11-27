import { act, cleanup, render } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TEST_WEEK, testWeek } from "../../../testSupport/liveWeek";
import { useLivePhase } from "./useLivePhase";
import { useLiveWindow } from "./useLiveWindow";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

/** A clock that moves on every reading, as a real one does between two renders. */
function movingClock() {
  let now = Date.UTC(2026, 10, 21, 15, 0);
  vi.spyOn(Date, "now").mockImplementation(() => (now += 1));
}

describe("the live window's clock", () => {
  it("closes both hooks exactly at the shared limit after opening less than one second before it", async () => {
    vi.useFakeTimers();
    const end = Date.parse("2026-11-21T20:30:00Z");
    vi.setSystemTime(end - 500);
    const calendar = testWeek().fixtures!;
    calendar.gameweeks[0]!.fixtures.push({
      ...calendar.gameweeks[0]!.fixtures[0]!,
      fixture_id: 104,
      kickoff_utc: null,
    });
    function Harness() {
      const phase = useLivePhase(calendar);
      const window = useLiveWindow(calendar, { unfinished: new Set([103]) });
      return (
        <output>
          {JSON.stringify({ on: phase.on, open: window.open, next: phase.nextGameweek })}
        </output>
      );
    }
    const shown = render(<Harness />);
    const state = () => JSON.parse(shown.getByRole("status").textContent!);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(state()).toMatchObject({ on: true, open: true, next: null });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(499);
    });
    expect(state()).toMatchObject({ on: true, open: true });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(state()).toMatchObject({ on: false, open: false, next: TEST_WEEK + 1 });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_000);
    });
    expect(state()).toMatchObject({ on: false, open: false, next: TEST_WEEK + 1 });
  });

  it("takes a caller's new filter object naming the same clubs as the same filter", async () => {
    vi.useFakeTimers();
    movingClock();
    let renders = 0;
    function Harness() {
      // A new object on every render, as a caller writing a literal passes it.
      useLiveWindow(null, { clubs: new Set([3, 1]), unfinished: null });
      useEffect(() => {
        renders += 1;
      });
      return null;
    }
    render(<Harness />);
    // Ten turns of the clock, each drawn before the next: a loop would draw once more each turn.
    for (let turn = 0; turn < 10; turn += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(10);
      });
    }
    // The first draw and the clock read for its filter: no render after another.
    expect(renders).toBeLessThanOrEqual(2);
  });

  it("reads the clock again when the filter names other clubs", async () => {
    vi.useFakeTimers();
    movingClock();
    let renders = 0;
    function Harness({ clubs }: { clubs: number[] }) {
      useLiveWindow(null, { clubs: new Set(clubs) });
      useEffect(() => {
        renders += 1;
      });
      return null;
    }
    const { rerender } = render(<Harness clubs={[1]} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    const before = renders;
    rerender(<Harness clubs={[1, 2]} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    // The new props' draw, then the clock read for the new filter.
    expect(renders - before).toBe(2);
  });
});
