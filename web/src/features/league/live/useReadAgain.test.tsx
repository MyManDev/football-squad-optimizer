/** A read made again while it is behind: after 1, 2, 4 and 8 minutes, then no more until reset. */

import { act, renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { READ_AGAIN_MS, useReadAgain } from "./useReadAgain";

afterEach(() => vi.useRealTimers());

const minutes = (count: number) =>
  act(() => {
    vi.advanceTimersByTime(count * 60_000);
  });

describe("a read made again", () => {
  it("waits 1, 2, 4 and 8 minutes between tries, then stops, and starts again on reset", () => {
    vi.useFakeTimers();
    const read = vi.fn();
    const { result } = renderHook(() => useReadAgain(true, read, false, 7));
    minutes(1);
    expect(read).toHaveBeenCalledTimes(1);
    minutes(2);
    expect(read).toHaveBeenCalledTimes(2);
    minutes(4);
    expect(read).toHaveBeenCalledTimes(3);
    minutes(8);
    expect(read).toHaveBeenCalledTimes(4);
    // Four tries, then none however long it waits.
    minutes(60);
    expect(read).toHaveBeenCalledTimes(READ_AGAIN_MS.length);
    // Yenile counts afresh: the next try a minute later.
    act(() => result.current());
    minutes(1);
    expect(read).toHaveBeenCalledTimes(READ_AGAIN_MS.length + 1);
  });

  it("reads nothing while the document is current or a read is on its way", () => {
    vi.useFakeTimers();
    const read = vi.fn();
    const { rerender } = renderHook(
      ({ behind, reading }) => useReadAgain(behind, read, reading, 7),
      { initialProps: { behind: false, reading: false } },
    );
    minutes(10);
    rerender({ behind: true, reading: true });
    minutes(10);
    expect(read).not.toHaveBeenCalled();
  });

  it("counts afresh for another rival", () => {
    vi.useFakeTimers();
    const read = vi.fn();
    const { rerender } = renderHook(({ key }) => useReadAgain(true, read, false, key), {
      initialProps: { key: 7 },
    });
    for (const wait of [1, 2, 4, 8]) minutes(wait);
    expect(read).toHaveBeenCalledTimes(4);
    rerender({ key: 8 });
    minutes(1);
    expect(read).toHaveBeenCalledTimes(5);
  });
});
