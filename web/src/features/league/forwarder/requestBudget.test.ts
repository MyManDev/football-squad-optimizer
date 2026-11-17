import { describe, expect, it } from "vitest";

import { createRequestBudget, type RequestLane } from "./requestBudget";

/** A clock and a timer the test moves by hand. */
function manualTime() {
  let at = 0;
  const timers: { due: number; run: () => void }[] = [];
  return {
    now: () => at,
    schedule: (run: () => void, delayMs: number) => {
      const timer = { due: at + delayMs, run };
      timers.push(timer);
      return () => {
        const index = timers.indexOf(timer);
        if (index >= 0) timers.splice(index, 1);
      };
    },
    async advance(ms: number) {
      at += ms;
      for (const timer of timers.filter((t) => t.due <= at)) {
        timers.splice(timers.indexOf(timer), 1);
        timer.run();
      }
      await Promise.resolve();
      await Promise.resolve();
    },
  };
}

function budgetWith(time: ReturnType<typeof manualTime>, pageLimit = 4, bulkLimit = 2) {
  return createRequestBudget({
    windowMs: 1000,
    pageLimit,
    bulkLimit,
    now: time.now,
    schedule: time.schedule,
  });
}

function track(
  budget: ReturnType<typeof createRequestBudget>,
  lane: RequestLane,
  log: string[],
  name: string,
) {
  const turn = budget.take(lane);
  if (turn === null) log.push(name);
  return (turn ?? Promise.resolve()).then(() => {
    if (turn !== null) log.push(name);
  });
}

async function settle() {
  for (let i = 0; i < 5; i += 1) await Promise.resolve();
}

describe("the forwarder's request budget", () => {
  it("starts at most the bulk limit of bulk reads in one window, then the rest as it frees", async () => {
    const time = manualTime();
    const budget = budgetWith(time);
    const log: string[] = [];
    for (const name of ["s1", "s2", "s3", "s4"]) void track(budget, "bulk", log, name);
    await settle();
    expect(log).toEqual(["s1", "s2"]);
    await time.advance(999);
    expect(log).toEqual(["s1", "s2"]);
    await time.advance(1);
    await settle();
    expect(log).toEqual(["s1", "s2", "s3", "s4"]);
  });

  it("lets page reads use the room above the bulk limit", async () => {
    const time = manualTime();
    const budget = budgetWith(time);
    const log: string[] = [];
    for (const name of ["s1", "s2", "s3"]) void track(budget, "bulk", log, name);
    for (const name of ["p1", "p2", "p3"]) void track(budget, "page", log, name);
    await settle();
    expect(log).toEqual(["s1", "s2", "p1", "p2"]);
  });

  it("starts a waiting page read before a bulk read that waited longer", async () => {
    const time = manualTime();
    const budget = budgetWith(time, 2, 2);
    const log: string[] = [];
    for (const name of ["s1", "s2", "s3"]) void track(budget, "bulk", log, name);
    void track(budget, "page", log, "p1");
    await settle();
    expect(log).toEqual(["s1", "s2"]);
    await time.advance(1000);
    await settle();
    expect(log).toEqual(["s1", "s2", "p1", "s3"]);
  });

  it("drops a read whose caller stopped while it waited, and keeps its turn for the next", async () => {
    const time = manualTime();
    const budget = budgetWith(time, 1, 1);
    const log: string[] = [];
    void track(budget, "page", log, "p1");
    const stop = new AbortController();
    const stopped = budget.take("page", stop.signal);
    void track(budget, "page", log, "p3");
    stop.abort();
    await expect(stopped!).rejects.toMatchObject({ name: "AbortError" });
    await time.advance(1000);
    await settle();
    expect(log).toEqual(["p1", "p3"]);
  });

  it("starts nothing, of either lane, while the rule's block is held", async () => {
    const time = manualTime();
    const budget = budgetWith(time);
    const log: string[] = [];
    budget.hold!(500);
    void track(budget, "page", log, "p1");
    void track(budget, "bulk", log, "s1");
    await settle();
    expect(log).toEqual([]);
    await time.advance(499);
    await settle();
    expect(log).toEqual([]);
    await time.advance(1);
    await settle();
    expect(log).toEqual(["p1", "s1"]);
  });

  it("refuses a read whose caller had already stopped", async () => {
    const budget = budgetWith(manualTime());
    const stop = new AbortController();
    stop.abort();
    await expect(budget.take("page", stop.signal)!).rejects.toMatchObject({ name: "AbortError" });
  });

  it("keeps the default shares under the rule's 50 with room for the backend's polls", async () => {
    const time = manualTime();
    const budget = createRequestBudget({ now: time.now, schedule: time.schedule });
    const log: string[] = [];
    for (let member = 1; member <= 50; member += 1) {
      void track(budget, "bulk", log, `season ${member}`);
    }
    for (let read = 1; read <= 15; read += 1) void track(budget, "page", log, `page ${read}`);
    await settle();
    expect(log.filter((name) => name.startsWith("season")).length).toBe(25);
    expect(log.length).toBe(35);
    await time.advance(10_000);
    await settle();
    expect(log.length).toBeLessThanOrEqual(70);
    expect(log.filter((name) => name.startsWith("page")).length).toBe(15);
  });

  it("starts a read with room at once, without a turn to wait for", () => {
    const budget = budgetWith(manualTime(), 1, 1);
    expect(budget.take("page")).toBeNull();
    expect(budget.take("page")).toBeInstanceOf(Promise);
  });

  it("refuses limits that would starve the page lane", () => {
    expect(() => createRequestBudget({ pageLimit: 2, bulkLimit: 3 })).toThrow(RangeError);
    expect(() => createRequestBudget({ windowMs: 0 })).toThrow(RangeError);
  });
});
