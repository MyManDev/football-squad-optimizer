/** The compute flow: request, wait with the published answer, land on the computed. */

import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import type {
  AdviceClient,
  AdviceJobStatus,
  AdviceReadResult,
  AdviceRequest,
  AdviceRequestResult,
} from "./adviceClient";
import { StaticOnlyAdviceClient } from "./adviceClient";
import { exampleTree } from "../../../testSupport/league";
import { sameAdviceRequest, useAdviceJob, type ComputePhase } from "./useAdviceJob";
import { AdviceResponseError } from "./adviceResponse";
import type { RequestOptions } from "../../../data/request";

afterEach(cleanup);
beforeEach(() => {
  vi.useFakeTimers();
  return () => vi.useRealTimers();
});

const REQUEST: AdviceRequest = {
  leagueId: 352490,
  entryId: 35249001,
  strategy: "garantici",
  window: 1,
};

class ScriptedClient implements AdviceClient {
  statuses: AdviceJobStatus["status"][] = [];
  // The published baseline is the example tree's document, as the static client reads it.
  private readonly published = new StaticOnlyAdviceClient(exampleTree.entryAdvice);

  readPublished(request: AdviceRequest, options?: RequestOptions): Promise<AdviceReadResult> {
    return this.published.readPublished(request, options);
  }

  async readAdvice(request: AdviceRequest): Promise<AdviceReadResult> {
    return {
      kind: "advice",
      envelope: mockEntryAdviceEnvelope(request.entryId, request.strategy, request.window),
      source: "api-cache",
    };
  }

  async requestAdvice(_request: AdviceRequest): Promise<AdviceRequestResult> {
    return { kind: "job", jobId: "job-1" };
  }

  async readJob(jobId: string): Promise<AdviceJobStatus> {
    const status = this.statuses.shift() ?? "completed";
    return { jobId, status };
  }
}

function Harness({
  client,
  allowBaseline = true,
}: {
  client: AdviceClient;
  allowBaseline?: boolean;
}) {
  const { state, compute, reset } = useAdviceJob(client, allowBaseline);
  return (
    <div>
      <output data-testid="phase">{describePhase(state)}</output>
      <output data-testid="standing">{describeStanding(state)}</output>
      <button type="button" onClick={reset}>
        reset
      </button>
      <button type="button" onClick={() => compute(REQUEST)}>
        go
      </button>
      <button type="button" onClick={() => compute({ ...REQUEST, window: 3 })}>
        go-window-3
      </button>
    </div>
  );
}

function describePhase(state: ComputePhase): string {
  switch (state.phase) {
    case "waiting":
      return `waiting:${state.status}:${state.fallback ? "with-fallback" : "no-fallback"}`;
    case "done":
      return `done:${state.source}`;
    default:
      return state.phase;
  }
}

function describeStanding(state: ComputePhase): string {
  if (state.phase !== "waiting") return "";
  const { queuePosition, progress, workers, answers } = state;
  return JSON.stringify({ queuePosition, progress, workers, answers });
}

const standing = () => JSON.parse(screen.getByTestId("standing").textContent || "null");

describe("useAdviceJob", () => {
  it("reset and unmount abort the actual request", async () => {
    const client = new ScriptedClient();
    const signals: AbortSignal[] = [];
    client.requestAdvice = async (_request: AdviceRequest, options?: RequestOptions) => {
      if (options?.signal) signals.push(options.signal);
      return new Promise(() => {});
    };
    const view = render(<Harness client={client} />);
    await act(async () => screen.getByText("go").click());
    expect(signals[0].aborted).toBe(false);
    await act(async () => screen.getByText("reset").click());
    expect(signals[0].aborted).toBe(true);
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
    await act(async () => screen.getByText("go").click());
    view.unmount();
    expect(signals[1].aborted).toBe(true);
  });

  it("a five-minute deadline ends a hanging custom client and fences its late answer", async () => {
    const client = new ScriptedClient();
    let finish!: (value: AdviceRequestResult) => void;
    client.requestAdvice = async () =>
      new Promise((resolve) => {
        finish = resolve;
      });
    render(<Harness client={client} />);
    await act(async () => screen.getByText("go").click());
    await act(async () => vi.advanceTimersByTimeAsync(300_000));
    expect(screen.getByTestId("phase")).toHaveTextContent("failed");
    await act(async () =>
      finish({
        kind: "advice",
        source: "api-cache",
        envelope: mockEntryAdviceEnvelope(REQUEST.entryId, REQUEST.strategy, REQUEST.window),
      }),
    );
    expect(screen.getByTestId("phase")).toHaveTextContent("failed");
  });
  it("a different season or week is a different request even for the same member", () => {
    const request = { ...REQUEST, season: "2026-27", gameweek: 3 };
    expect(sameAdviceRequest(request, { ...request })).toBe(true);
    expect(sameAdviceRequest(request, { ...request, gameweek: 4 })).toBe(false);
    expect(sameAdviceRequest(request, { ...request, season: "2027-28" })).toBe(false);
  });

  it("does not show another member's result when a custom client misroutes a cache hit", async () => {
    const client = new ScriptedClient();
    client.requestAdvice = async () => ({
      kind: "advice",
      envelope: mockEntryAdviceEnvelope(999, "garantici", 1),
      source: "api-cache",
    });
    render(<Harness client={client} />);
    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
    });
    expect(screen.getByTestId("phase").textContent).toBe("failed");
  });

  it("does not keep polling a malformed job response", async () => {
    const client = new ScriptedClient();
    client.readJob = async () => {
      throw new AdviceResponseError("Wrong job identity");
    };
    render(<Harness client={client} />);
    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.getByTestId("phase").textContent).toBe("failed");
  });

  it("walks queued to running to completed, showing the published answer meanwhile", async () => {
    const client = new ScriptedClient();
    client.statuses = ["running", "completed"];
    render(<Harness client={client} />);

    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
      await Promise.resolve();
    });
    expect(screen.getByTestId("phase").textContent).toBe("waiting:queued:with-fallback");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.getByTestId("phase").textContent).toBe("waiting:running:with-fallback");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.getByTestId("phase").textContent).toBe("done:api-cache");
  });

  it("follows what the service last said about the wait, and counts its answers", async () => {
    const client = new ScriptedClient();
    const views: Omit<AdviceJobStatus, "jobId">[] = [
      { status: "queued", queuePosition: 2, workers: { busy: 1, total: 1 } },
      { status: "queued", queuePosition: 0, workers: { busy: 1, total: 1 } },
      { status: "running", progress: { done: 1, total: 3 }, workers: { busy: 1, total: 1 } },
      { status: "running" },
    ];
    client.readJob = async (jobId) => ({ jobId, ...(views.shift() ?? { status: "completed" }) });
    render(<Harness client={client} />);

    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
      await Promise.resolve();
    });
    expect(standing()).toEqual({});

    const nextAnswer = () =>
      act(async () => {
        await vi.advanceTimersByTimeAsync(2100);
      });
    await nextAnswer();
    expect(standing()).toEqual({ queuePosition: 2, workers: { busy: 1, total: 1 }, answers: 1 });
    expect(screen.getByTestId("phase").textContent).toBe("waiting:queued:with-fallback");

    await nextAnswer();
    expect(standing()).toEqual({ queuePosition: 0, workers: { busy: 1, total: 1 }, answers: 2 });

    await nextAnswer();
    expect(standing()).toEqual({
      progress: { done: 1, total: 3 },
      workers: { busy: 1, total: 1 },
      answers: 3,
    });
    expect(screen.getByTestId("phase").textContent).toBe("waiting:running:with-fallback");

    // What the service stops saying is not kept, but for the count of the attempt running.
    await nextAnswer();
    expect(standing()).toEqual({ progress: { done: 1, total: 3 }, answers: 4 });

    await nextAnswer();
    expect(screen.getByTestId("phase").textContent).toBe("done:api-cache");
    expect(screen.getByTestId("standing").textContent).toBe("");
  });

  it("keeps the count through a poll that could not read it, for the same attempt", async () => {
    const client = new ScriptedClient();
    const views: Omit<AdviceJobStatus, "jobId">[] = [
      { status: "running", attempt: 1, progress: { done: 2, total: 3 } },
      { status: "running", attempt: 1 },
      { status: "running", attempt: 2 },
      { status: "running", attempt: 2, progress: { done: 0, total: 3 } },
      { status: "queued", attempt: 2 },
      { status: "running", attempt: 2 },
    ];
    client.readJob = async (jobId) => ({ jobId, ...views.shift()! });
    render(<Harness client={client} />);
    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
      await Promise.resolve();
    });
    const said = async () => {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2100);
      });
      return standing().progress;
    };
    expect(await said()).toEqual({ done: 2, total: 3 });
    expect(await said()).toEqual({ done: 2, total: 3 });
    // A new attempt starts again, and a job back in the queue has no count.
    expect(await said()).toBeUndefined();
    expect(await said()).toEqual({ done: 0, total: 3 });
    expect(await said()).toBeUndefined();
    expect(await said()).toBeUndefined();
  });

  it("takes a job's first word from the answer that accepted it", async () => {
    const client = new ScriptedClient();
    client.requestAdvice = async () => ({ kind: "job", jobId: "job-1", status: "running" });
    client.statuses = ["running"];
    render(<Harness client={client} />);
    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
      await Promise.resolve();
    });
    expect(screen.getByTestId("phase").textContent).toBe("waiting:running:with-fallback");
  });

  it("a poll with no answer changes nothing about the wait", async () => {
    const client = new ScriptedClient();
    let reachable = true;
    client.readJob = async (jobId) => {
      if (!reachable) throw new TypeError("Failed to fetch");
      return { jobId, status: "running", progress: { done: 1, total: 3 } };
    };
    render(<Harness client={client} />);

    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
      await Promise.resolve();
    });
    const nextPoll = () =>
      act(async () => {
        await vi.advanceTimersByTimeAsync(2100);
      });
    await nextPoll();
    const said = { progress: { done: 1, total: 3 }, answers: 1 };
    expect(standing()).toEqual(said);

    reachable = false;
    await nextPoll();
    await nextPoll();
    expect(standing()).toEqual(said);
    expect(screen.getByTestId("phase").textContent).toBe("waiting:running:with-fallback");

    reachable = true;
    await nextPoll();
    expect(standing()).toEqual({ ...said, answers: 2 });
  });

  it("a failed job is a failed phase, not a spinner", async () => {
    const client = new ScriptedClient();
    client.statuses = ["failed"];
    render(<Harness client={client} />);

    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.getByTestId("phase").textContent).toBe("failed");
  });

  it("an immediate hit lands without any waiting phase", async () => {
    const client = new ScriptedClient();
    client.requestAdvice = async () => ({
      kind: "advice",
      envelope: mockEntryAdviceEnvelope(35249001, "garantici", 1),
      source: "api-cache",
    });
    render(<Harness client={client} />);

    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
      await Promise.resolve();
    });
    expect(screen.getByTestId("phase").textContent).toBe("done:api-cache");
  });

  it("a static-only world says unavailable for the uncomputed", async () => {
    const client = new ScriptedClient();
    client.requestAdvice = async () => ({ kind: "unavailable" });
    render(<Harness client={client} />);

    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
      await Promise.resolve();
    });
    expect(screen.getByTestId("phase").textContent).toBe("unavailable");
  });

  it("a completed job whose answer cannot be read is a failed phase, not a wait", async () => {
    const client = new ScriptedClient();
    client.statuses = ["completed"];
    client.readAdvice = async () => {
      throw new Error("cache read failed");
    };
    render(<Harness client={client} />);

    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
      await Promise.resolve();
    });
    expect(screen.getByTestId("phase").textContent).toBe("waiting:queued:with-fallback");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.getByTestId("phase").textContent).toBe("failed");
  });

  it("a stale read rejection cannot touch a newer request's state", async () => {
    const client = new ScriptedClient();
    client.statuses = ["completed"];
    let rejectStaleRead: (error: Error) => void = () => {};
    client.requestAdvice = async (request) =>
      request.window === 3
        ? {
            kind: "advice",
            envelope: mockEntryAdviceEnvelope(request.entryId, request.strategy, 3),
            source: "api-cache",
          }
        : { kind: "job", jobId: "job-1" };
    client.readAdvice = (request) =>
      request.window === 3
        ? Promise.resolve<AdviceReadResult>({
            kind: "advice",
            envelope: mockEntryAdviceEnvelope(request.entryId, request.strategy, 3),
            source: "api-cache",
          })
        : new Promise<AdviceReadResult>((_resolve, reject) => {
            rejectStaleRead = reject;
          });
    render(<Harness client={client} />);

    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
      await Promise.resolve();
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100); // the job completes; its read is still pending
    });
    expect(screen.getByTestId("phase").textContent).toBe("waiting:queued:with-fallback");

    await act(async () => {
      screen.getByRole("button", { name: "go-window-3" }).click();
      await Promise.resolve();
    });
    expect(screen.getByTestId("phase").textContent).toBe("done:api-cache");

    await act(async () => {
      rejectStaleRead(new Error("late"));
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId("phase").textContent).toBe("done:api-cache");
  });
});

it("does not probe a saf-puan baseline the member index did not authorize", async () => {
  const read = vi.spyOn(StaticOnlyAdviceClient.prototype, "readAdvice");
  try {
    render(<Harness client={new ScriptedClient()} allowBaseline={false} />);
    await act(async () => {
      screen.getByRole("button", { name: "go" }).click();
    });
    expect(screen.getByTestId("phase")).toHaveTextContent("waiting:queued:no-fallback");
    expect(read).not.toHaveBeenCalled();
  } finally {
    read.mockRestore();
  }
});
