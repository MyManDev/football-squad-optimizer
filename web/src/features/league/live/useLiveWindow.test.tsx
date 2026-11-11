import { act, cleanup, render } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
