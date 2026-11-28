import { afterEach, describe, expect, it, vi } from "vitest";
import { guardedBrowserSolve } from "./watchdog.mjs";

afterEach(() => vi.useRealTimers());
describe("external browser watchdog", () => {
  it("closes only the supplied own context when the browser never replies", async () => {
    vi.useFakeTimers();
    const closeOwnContext = vi.fn().mockResolvedValue(undefined);
    const pending = guardedBrowserSolve(() => new Promise(() => {}), closeOwnContext, 100);
    await vi.advanceTimersByTimeAsync(100);
    const answer = await pending;
    expect(answer.reply.kind).toBe("timeout");
    expect(answer.elapsed_seconds).toBeNull();
    expect(answer.censored_at_seconds).toBeGreaterThanOrEqual(0);
    expect(closeOwnContext).toHaveBeenCalledTimes(1);
  });
  it("preserves the completed inner and outside clocks without closing its context", async () => {
    const closeOwnContext = vi.fn();
    const result = await guardedBrowserSolve(
      async () => ({ reply: { kind: "answer" }, elapsed_seconds: 2 }),
      closeOwnContext,
      1000,
    );
    expect(result.elapsed_seconds).toBe(2);
    expect(result.outer_elapsed_seconds).toBeGreaterThanOrEqual(0);
    expect(closeOwnContext).not.toHaveBeenCalled();
  });
});
