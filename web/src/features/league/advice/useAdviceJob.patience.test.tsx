/**
 * The wait, honestly: one key per click, patience that follows the window, fewer polls
 * after the first minute, a failure that keeps its reason, and a job id that survives a
 * reload for the same selection and no other.
 */

import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import type {
  AdviceClient,
  AdviceJobStatus,
  AdviceReadResult,
  AdviceRequest,
  AdviceRequestOptions,
  AdviceRequestResult,
} from "./adviceClient";
import { AdviceApiError, StaticOnlyAdviceClient } from "./adviceClient";
import { adviceRequestKey, recallJob, rememberJob } from "./adviceJobStore";
import type { RequestOptions } from "../../../data/request";
import { exampleTree } from "../../../testSupport/league";
import {
  ANSWER_MISMATCH,
  PATIENCE_EXHAUSTED,
  PATIENCE_MS,
  QUEUE_PATIENCE_MS,
  useAdviceJob,
  type ComputePhase,
} from "./useAdviceJob";

afterEach(cleanup);
beforeEach(() => {
  vi.useFakeTimers();
  return () => vi.useRealTimers();
});

const REQUEST: AdviceRequest = {
  leagueId: 352490,
  entryId: 35249001,
  strategy: "saf-puan",
  window: 1,
  top100Weight: 0,
  managersWord: false,
};

class SlowClient implements AdviceClient {
  polls: number[] = [];
  private readonly published = new StaticOnlyAdviceClient(exampleTree.entryAdvice);
  readPublished = (request: AdviceRequest, options?: RequestOptions) =>
    this.published.readPublished(request, options);
  keys: (string | undefined)[] = [];
  job: AdviceJobStatus["status"] | { errorCode: string } | Error = "running";
  readAdvice = async (request: AdviceRequest): Promise<AdviceReadResult> => ({
    kind: "advice",
    envelope: mockEntryAdviceEnvelope(request.entryId, request.strategy, request.window),
    source: "api-cache",
  });
  requestAdvice = async (
    _request: AdviceRequest,
    options?: AdviceRequestOptions,
  ): Promise<AdviceRequestResult> => {
    this.keys.push(options?.idempotencyKey);
    return { kind: "job", jobId: "advice-0123456789abcdef-1" };
  };
  readJob = async (jobId: string): Promise<AdviceJobStatus> => {
    this.polls.push(Date.now());
    if (this.job instanceof Error) throw this.job;
    if (typeof this.job === "object") {
      return { jobId, status: "failed", errorCode: this.job.errorCode };
    }
    return { jobId, status: this.job };
  };
}

function Harness({
  client,
  request = REQUEST,
  allowBaseline = false,
  expectedSnapshotId,
}: {
  client: AdviceClient;
  request?: AdviceRequest;
  allowBaseline?: boolean;
  expectedSnapshotId?: string;
}) {
  const { state, compute, resume, readCached } = useAdviceJob(
    client,
    allowBaseline,
    expectedSnapshotId,
    true,
  );
  return (
    <div>
      <output data-testid="phase">{describePhase(state)}</output>
      <button type="button" onClick={() => compute(request)}>
        go
      </button>
      <button type="button" onClick={() => resume?.(request)}>
        resume
      </button>
      <button type="button" onClick={() => readCached?.(request)}>
        read cache
      </button>
    </div>
  );
}

function describePhase(state: ComputePhase): string {
  if (state.phase === "failed") {
    return `failed:${state.reason ?? ""}:${state.retryAfterSeconds ?? ""}`;
  }
  if (state.phase === "unavailable") return `unavailable:${state.reason ?? ""}`;
  if (state.phase === "waiting") return `waiting:${state.status}:${state.jobId}`;
  return state.phase;
}

async function click(name: string): Promise<void> {
  await act(async () => {
    screen.getByRole("button", { name }).click();
    await Promise.resolve();
  });
}

const phase = () => screen.getByTestId("phase").textContent;

describe("patience", () => {
  it("exceeds each window's measured solve", () => {
    expect(PATIENCE_MS[1]).toBeGreaterThanOrEqual(3 * 60_000);
    expect(PATIENCE_MS[3]).toBeGreaterThanOrEqual(6 * 60_000);
    expect(PATIENCE_MS[5]).toBeGreaterThanOrEqual(10 * 60_000);
    // Measured: about ninety seconds at three weeks, about three and a half minutes at five.
    expect(PATIENCE_MS[3]).toBeGreaterThan(2 * 90_000);
    expect(PATIENCE_MS[5]).toBeGreaterThan(2 * 210_000);
  });

  it("resumes a late queued three-week job and gives its solve the full running budget", async () => {
    const request = { ...REQUEST, window: 3 } as const;
    const client = new SlowClient();
    client.job = "queued";
    const view = render(<Harness client={client} request={request} />);
    await click("go");
    await act(async () => vi.advanceTimersByTimeAsync(PATIENCE_MS[3] + 30_000));
    expect(phase()).toBe("waiting:queued:advice-0123456789abcdef-1");
    expect(recallJob(request)?.runningSince).toBeUndefined();
    view.unmount();

    client.job = "running";
    const runningSince = Date.now();
    render(<Harness client={client} request={request} />);
    await click("resume");
    expect(recallJob(request)?.runningSince).toBe(runningSince);
    await act(async () => vi.advanceTimersByTimeAsync(PATIENCE_MS[3] - 10_000));
    expect(phase()).toBe("waiting:running:advice-0123456789abcdef-1");
    client.job = "completed";
    await act(async () => vi.advanceTimersByTimeAsync(5000));
    expect(phase()).toBe("done");
    expect(client.keys).toHaveLength(1);
  });

  it("expires a job that stays queued beyond the queue budget", async () => {
    const client = new SlowClient();
    client.job = "queued";
    render(<Harness client={client} />);
    await click("go");
    await act(async () => vi.advanceTimersByTimeAsync(QUEUE_PATIENCE_MS));
    expect(phase()).toBe(`failed:${PATIENCE_EXHAUSTED}:`);
    expect(recallJob(REQUEST)).toBeNull();
  });

  it.each([
    [1, 3],
    [3, 6],
    [5, 10],
  ] as const)("waits %i-week plans for %i minutes, then says why it stopped", async (window, m) => {
    const client = new SlowClient();
    render(<Harness client={client} request={{ ...REQUEST, window }} />);
    await click("go");
    await act(async () => vi.advanceTimersByTimeAsync(m * 60_000 - 6000));
    expect(phase()).toBe("waiting:running:advice-0123456789abcdef-1");
    await act(async () => vi.advanceTimersByTimeAsync(12_000));
    expect(phase()).toBe(`failed:${PATIENCE_EXHAUSTED}:`);
    expect(recallJob({ ...REQUEST, window })).toBeNull();
  });

  it("polls every two seconds for a minute, then every five", async () => {
    const client = new SlowClient();
    render(<Harness client={client} request={{ ...REQUEST, window: 5 }} />);
    await click("go");
    const started = Date.now();
    await act(async () => vi.advanceTimersByTimeAsync(120_000));
    const gaps = client.polls.map((at, i) => at - (client.polls[i - 1] ?? started));
    const firstMinute = gaps.filter((_gap, i) => client.polls[i]! - started <= 60_000);
    const later = gaps.filter((_gap, i) => client.polls[i]! - started > 62_000);
    expect(firstMinute.length).toBeGreaterThanOrEqual(29);
    expect(new Set(firstMinute)).toEqual(new Set([2000]));
    expect(later.length).toBeGreaterThanOrEqual(10);
    expect(new Set(later)).toEqual(new Set([5000]));
  });
});

describe("a click", () => {
  it("sends one fresh key, and the next click another", async () => {
    const client = new SlowClient();
    client.job = "completed";
    render(<Harness client={client} />);
    await click("go");
    await act(async () => vi.advanceTimersByTimeAsync(2100));
    expect(phase()).toBe("done");
    await click("go");
    expect(client.keys).toHaveLength(2);
    expect(client.keys[0]).toMatch(/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/);
    expect(client.keys[1]).not.toBe(client.keys[0]);
  });
});

describe("a failure keeps its reason", () => {
  it("from the job view's error code", async () => {
    const client = new SlowClient();
    client.job = { errorCode: "SWITCH_INPUTS_CHANGED" };
    render(<Harness client={client} />);
    await click("go");
    await act(async () => vi.advanceTimersByTimeAsync(2100));
    expect(phase()).toBe("failed:SWITCH_INPUTS_CHANGED:");
    expect(recallJob(REQUEST)).toBeNull();
  });

  it("from a refused request, with the wait the service asked for", async () => {
    const client = new SlowClient();
    client.requestAdvice = async () => {
      throw new AdviceApiError(429, "RATE_LIMITED", 60);
    };
    render(<Harness client={client} />);
    await click("go");
    expect(phase()).toBe("failed:RATE_LIMITED:60");
  });

  it("from an unavailable service", async () => {
    const client = new SlowClient();
    client.requestAdvice = async () => ({ kind: "unavailable", reason: "NOT_READY" });
    render(<Harness client={client} />);
    await click("go");
    expect(phase()).toBe("unavailable:NOT_READY");
  });

  it("from an answer solved under other switches than the ones asked", async () => {
    const client = new SlowClient();
    client.job = "completed";
    render(<Harness client={client} request={{ ...REQUEST, top100Weight: 20 }} />);
    await click("go");
    await act(async () => vi.advanceTimersByTimeAsync(2100));
    expect(phase()).toBe(`failed:${ANSWER_MISMATCH}:`);
  });
});

describe("a reload", () => {
  it("remembers the job under the question it answers, and only while it is open", async () => {
    const client = new SlowClient();
    render(<Harness client={client} />);
    await click("go");
    expect(recallJob(REQUEST)).toMatchObject({ jobId: "advice-0123456789abcdef-1" });
    expect(recallJob({ ...REQUEST, top100Weight: 20 })).toBeNull();
    expect(recallJob({ ...REQUEST, window: 3 })).toBeNull();
    expect(adviceRequestKey(REQUEST)).not.toBe(
      adviceRequestKey({ ...REQUEST, managersWord: true }),
    );
    client.job = "completed";
    await act(async () => vi.advanceTimersByTimeAsync(2100));
    expect(phase()).toBe("done");
    expect(recallJob(REQUEST)).toBeNull();
  });

  it("resumes polling the remembered job without asking again", async () => {
    rememberJob(REQUEST, { jobId: "advice-feedfacefeedface-2", startedAt: Date.now() - 30_000 });
    const client = new SlowClient();
    render(<Harness client={client} />);
    expect(phase()).toBe("idle");
    await click("resume");
    expect(phase()).toBe("waiting:running:advice-feedfacefeedface-2");
    client.job = "completed";
    await act(async () => vi.advanceTimersByTimeAsync(2100));
    expect(phase()).toBe("done");
    expect(client.keys).toEqual([]); // no POST
    expect(recallJob(REQUEST)).toBeNull();
  });

  it("names no word for a remembered job until the service has, and asks at once", async () => {
    // Past its first minute, when the polls are five seconds apart.
    rememberJob(REQUEST, { jobId: "advice-feedfacefeedface-2", startedAt: Date.now() - 120_000 });
    const client = new SlowClient();
    let answer: (view: AdviceJobStatus) => void = () => {};
    const read = vi.fn(
      () =>
        new Promise<AdviceJobStatus>((resolve) => {
          answer = resolve;
        }),
    );
    client.readJob = read;
    render(<Harness client={client} />);
    await click("resume");
    expect(phase()).toBe("waiting:null:advice-feedfacefeedface-2");
    expect(read).toHaveBeenCalledTimes(1);
    await act(async () => answer({ jobId: "advice-feedfacefeedface-2", status: "running" }));
    expect(phase()).toBe("waiting:running:advice-feedfacefeedface-2");
    expect(client.keys).toEqual([]); // no POST
  });

  it("asks about a remembered job once, even when the baseline's read uses up its patience", async () => {
    const runningSince = Date.now() - (PATIENCE_MS[1] - 2000);
    rememberJob(REQUEST, {
      jobId: "advice-feedfacefeedface-2",
      startedAt: runningSince,
      runningSince,
    });
    const client = new SlowClient();
    client.readPublished = () =>
      new Promise((resolve) => setTimeout(() => resolve({ kind: "not-computed" }), 3000));
    client.job = "completed";
    render(<Harness client={client} allowBaseline />);
    await click("resume");
    await act(async () => vi.advanceTimersByTimeAsync(3100));
    expect(client.polls).toHaveLength(1);
    expect(phase()).toBe("done");
  });

  it("stays silent about a remembered job while the service does not answer", async () => {
    rememberJob(REQUEST, { jobId: "advice-feedfacefeedface-2", startedAt: Date.now() - 30_000 });
    const client = new SlowClient();
    client.job = new TypeError("Failed to fetch");
    render(<Harness client={client} />);
    await click("resume");
    await act(async () => vi.advanceTimersByTimeAsync(4100));
    expect(phase()).toBe("waiting:null:advice-feedfacefeedface-2");
    client.job = "queued";
    await act(async () => vi.advanceTimersByTimeAsync(2100));
    expect(phase()).toBe("waiting:queued:advice-feedfacefeedface-2");
  });

  it("keeps the running deadline through a reload and a retry in the same queue", async () => {
    rememberJob(REQUEST, {
      jobId: "advice-feedfacefeedface-2",
      startedAt: Date.now() - 300_000,
      runningSince: Date.now() - 170_000,
    });
    const client = new SlowClient();
    client.job = "queued";
    render(<Harness client={client} />);
    await click("resume");
    await act(async () => vi.advanceTimersByTimeAsync(16_000));
    expect(phase()).toBe(`failed:${PATIENCE_EXHAUSTED}:`);
  });

  it("drops a job that is too old, unreadable, or gone from the service", async () => {
    const client = new SlowClient();
    render(<Harness client={client} />);
    rememberJob(REQUEST, { jobId: "advice-old", startedAt: Date.now() - QUEUE_PATIENCE_MS - 1 });
    await click("resume");
    expect(phase()).toBe("idle");
    expect(recallJob(REQUEST)).toBeNull();

    sessionStorage.setItem(`squadopt.advice-job:${adviceRequestKey(REQUEST)}`, "{not json");
    await click("resume");
    expect(phase()).toBe("idle");

    rememberJob(REQUEST, { jobId: "advice-gone", startedAt: Date.now() });
    client.job = new AdviceApiError(404, "NOT_FOUND");
    const read = vi.spyOn(client, "readAdvice").mockResolvedValue({ kind: "not-computed" });
    await click("resume");
    await act(async () => vi.advanceTimersByTimeAsync(2100));
    expect(phase()).toBe("idle"); // a fresh visit, not this visit's failure
    expect(read).toHaveBeenCalledTimes(1);
    expect(client.keys).toEqual([]);
    expect(recallJob(REQUEST)).toBeNull();
  });

  it("works where the browser gives the page no storage at all", async () => {
    const blocked = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    try {
      const client = new SlowClient();
      client.job = "completed";
      render(<Harness client={client} />);
      await click("go");
      await act(async () => vi.advanceTimersByTimeAsync(2100));
      expect(phase()).toBe("done");
    } finally {
      blocked.mockRestore();
    }
  });
});

it("restores cached advice only from the requested capture in strict mode", async () => {
  const client = new SlowClient();
  const capture = "fixture-capture";
  let snapshot: string | null = null;
  client.readAdvice = async (request) => {
    const envelope = mockEntryAdviceEnvelope(request.entryId, request.strategy, request.window);
    envelope.payload.source_snapshot_id = snapshot;
    return { kind: "advice", envelope, source: "api-cache" };
  };
  render(<Harness client={client} expectedSnapshotId={capture} />);
  await click("read cache");
  expect(phase()).toBe("idle");
  snapshot = "previous-capture";
  await click("read cache");
  expect(phase()).toBe("idle");
  snapshot = capture;
  await click("read cache");
  expect(phase()).toBe("done");
  expect(client.keys).toEqual([]);
});
