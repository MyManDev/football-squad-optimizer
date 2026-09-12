import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cancellableDelay, withRequestDeadline } from "./request";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

it("bounds a transport that ignores cancellation and aborts its signal", async () => {
  let captured: AbortSignal | undefined;
  const result = withRequestDeadline(
    (signal) => {
      captured = signal;
      return new Promise<never>(() => {});
    },
    { timeoutMs: 20 },
  );
  const assertion = expect(result).rejects.toMatchObject({ name: "TimeoutError" });
  await vi.advanceTimersByTimeAsync(20);
  await assertion;
  expect(captured?.aborted).toBe(true);
  expect(vi.getTimerCount()).toBe(0);
});

it("does not start a request already cancelled by its caller", async () => {
  const controller = new AbortController();
  controller.abort();
  const operation = vi.fn();
  await expect(withRequestDeadline(operation, { signal: controller.signal })).rejects.toMatchObject(
    { name: "AbortError" },
  );
  expect(operation).not.toHaveBeenCalled();
  expect(vi.getTimerCount()).toBe(0);
});

it("cancels a poll delay immediately and clears its timer", async () => {
  const controller = new AbortController();
  const waiting = cancellableDelay(2000, controller.signal);
  controller.abort();
  await waiting;
  expect(vi.getTimerCount()).toBe(0);
});
