/**
 * How many forwarder requests one tab may start in a short window. The zone's rate-limiting
 * rule counts every request under `/api/v1/` per visitor address: 50 in 10 seconds, then a
 * block of 10 seconds (ADR 0012, section 8). A forwarded league's scoreboard reads one season
 * per member of the standings page, up to 50 at once, so without a budget one member page
 * could spend the whole allowance by itself and have the backend's polls refused with it.
 *
 * Two lanes share one window. A page read (a table, a bundle, a live week) starts while fewer
 * than `pageLimit` requests started in the window. A bulk read (a member's season for the
 * scoreboard) starts while fewer than `bulkLimit` did and no page read is waiting, so the
 * reads a page shows first are never queued behind the scoreboard. The difference between
 * the two limits and the rule's 50 is left to the backend: one followed job polls five times
 * in 10 seconds.
 */

export type RequestLane = "page" | "bulk";

export interface RequestBudget {
  /**
   * `null` when a request of this lane may start now, counted as started; otherwise a promise
   * that resolves when it may start and rejects when `signal` aborts first. Starting at once
   * without a promise keeps a read that has room in the order it was asked in.
   */
  take(lane: RequestLane, signal?: AbortSignal): Promise<void> | null;
  /**
   * The rule has refused a read: no read of either lane starts for `durationMs`, so the
   * reads already asked for wait out the block instead of each being refused in turn.
   */
  hold?(durationMs: number): void;
}

export interface RequestBudgetOptions {
  windowMs?: number;
  pageLimit?: number;
  bulkLimit?: number;
  /** The clock; the page's own unless a test injects one. */
  now?: () => number;
  /** The timer; the page's own unless a test injects one. */
  schedule?: (run: () => void, delayMs: number) => () => void;
}

/** The rule's window, and the shares of its 50 requests this tab's forwarder reads may use. */
export const BUDGET_WINDOW_MS = 10_000;
export const PAGE_READ_LIMIT = 35;
export const BULK_READ_LIMIT = 25;

interface Waiter {
  lane: RequestLane;
  grant: () => void;
}

function abortError(): DOMException {
  return new DOMException("The read was stopped while it waited for its turn.", "AbortError");
}

export function createRequestBudget({
  windowMs = BUDGET_WINDOW_MS,
  pageLimit = PAGE_READ_LIMIT,
  bulkLimit = BULK_READ_LIMIT,
  now = () => Date.now(),
  schedule = (run, delayMs) => {
    const timer = setTimeout(run, delayMs);
    return () => clearTimeout(timer);
  },
}: RequestBudgetOptions = {}): RequestBudget {
  if (
    !Number.isFinite(windowMs) ||
    windowMs <= 0 ||
    !Number.isSafeInteger(pageLimit) ||
    !Number.isSafeInteger(bulkLimit) ||
    bulkLimit < 1 ||
    pageLimit < bulkLimit
  ) {
    throw new RangeError("A request budget needs a positive window and 1 <= bulk <= page.");
  }
  const started: number[] = [];
  const waiting: Waiter[] = [];
  let cancelTimer: (() => void) | null = null;
  // While the rule blocks this address, nothing starts before this time.
  let heldUntil = 0;

  function inWindow(at: number): number {
    while (started.length > 0 && started[0]! <= at - windowMs) started.shift();
    return started.length;
  }

  function limitOf(lane: RequestLane): number {
    return lane === "page" ? pageLimit : bulkLimit;
  }

  /** Start every waiter the window allows, page reads first, and wake again when one frees. */
  function pump(): void {
    cancelTimer?.();
    cancelTimer = null;
    for (;;) {
      const at = now();
      if (waiting.length > 0 && at < heldUntil) {
        cancelTimer = schedule(pump, Math.max(1, heldUntil - at));
        return;
      }
      const used = inWindow(at);
      const index = waiting.findIndex((waiter) => waiter.lane === "page");
      const next = index >= 0 ? index : waiting.length > 0 ? 0 : -1;
      if (next < 0) return;
      const waiter = waiting[next]!;
      if (used >= limitOf(waiter.lane)) {
        // The oldest start in the window leaves it first; a bulk read waits for its own limit.
        const frees = started[used - limitOf(waiter.lane)]! + windowMs;
        cancelTimer = schedule(pump, Math.max(1, frees - at));
        return;
      }
      waiting.splice(next, 1);
      started.push(at);
      waiter.grant();
    }
  }

  return {
    take(lane, signal) {
      if (signal?.aborted) return Promise.reject(abortError());
      const at = now();
      if (waiting.length === 0 && at >= heldUntil && inWindow(at) < limitOf(lane)) {
        started.push(at);
        return null;
      }
      return new Promise<void>((resolve, reject) => {
        const waiter: Waiter = {
          lane,
          grant: () => {
            signal?.removeEventListener("abort", stop);
            resolve();
          },
        };
        function stop(): void {
          const index = waiting.indexOf(waiter);
          if (index >= 0) waiting.splice(index, 1);
          reject(abortError());
          pump();
        }
        signal?.addEventListener("abort", stop, { once: true });
        waiting.push(waiter);
        pump();
      });
    },
    hold(durationMs) {
      if (!Number.isFinite(durationMs) || durationMs <= 0) return;
      heldUntil = Math.max(heldUntil, now() + durationMs);
      pump();
    },
  };
}

/** A budget that never waits, for a client a test drives by hand. */
export const UNLIMITED_BUDGET: RequestBudget = { take: () => null };
