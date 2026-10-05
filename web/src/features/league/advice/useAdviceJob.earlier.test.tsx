/**
 * A second attempt for the same selection carries the answer the first one gave, one press
 * is one request, and a new selection starts without the old one's state.
 */

import { useEffect } from "react";

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
import { AdviceApiError, StaticOnlyAdviceClient } from "./adviceClient";
import { useAdviceJob, type ComputePhase } from "./useAdviceJob";
import type { RequestOptions } from "../../../data/request";
import { exampleTree } from "../../../testSupport/league";

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
const OTHER: AdviceRequest = { ...REQUEST, window: 3 };

class Client implements AdviceClient {
  posts: AdviceRequest[] = [];
  answer: AdviceRequestResult | Error = { kind: "job", jobId: "job-1" };
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

  async requestAdvice(request: AdviceRequest): Promise<AdviceRequestResult> {
    this.posts.push(request);
    if (this.answer instanceof Error) throw this.answer;
    return this.answer;
  }

  async readJob(jobId: string): Promise<AdviceJobStatus> {
    return { jobId, status: "completed" };
  }
}

function Harness({
  client,
  onState,
}: {
  client: AdviceClient;
  onState: (state: ComputePhase) => void;
}) {
  const { state, compute, readCached, reset } = useAdviceJob(client, false);
  useEffect(() => {
    onState(state);
  }, [state, onState]);
  const earlier = "earlier" in state ? state.earlier : undefined;
  return (
    <div>
      <output data-testid="phase">{state.phase}</output>
      <output data-testid="earlier">{earlier ? earlier.envelope.payload.window : "none"}</output>
      <button type="button" onClick={() => readCached?.(REQUEST)}>
        read
      </button>
      <button type="button" onClick={() => compute(REQUEST)}>
        go
      </button>
      <button type="button" onClick={() => compute(OTHER)}>
        go-other
      </button>
      <button type="button" onClick={reset}>
        reset
      </button>
    </div>
  );
}

describe("the answer a selection already received", () => {
  it("is carried by a later attempt that is refused, and by one that is waiting", async () => {
    const client = new Client();
    const seen = { latest: { phase: "idle" } as ComputePhase };
    render(
      <Harness
        client={client}
        onState={(state) => {
          seen.latest = state;
        }}
      />,
    );
    await act(async () => screen.getByText("read").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("done");
    const first = seen.latest.phase === "done" ? seen.latest.envelope : null;
    expect(first).not.toBeNull();

    // Refused: the state is the failure, and the first answer rides with it.
    client.answer = new AdviceApiError(429, "QUEUE_FULL", 30);
    await act(async () => screen.getByText("go").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("failed");
    expect(seen.latest.phase === "failed" && seen.latest.earlier?.envelope).toBe(first);
    expect(seen.latest.phase === "failed" && seen.latest.retryAfterSeconds).toBe(30);

    // A job that never completes: the wait carries it too.
    client.answer = { kind: "job", jobId: "job-2" };
    client.readJob = async (jobId) => ({ jobId, status: "running" });
    await act(async () => screen.getByText("go").click());
    await act(async () => vi.advanceTimersByTimeAsync(5_000));
    expect(screen.getByTestId("phase")).toHaveTextContent("waiting");
    expect(seen.latest.phase === "waiting" && seen.latest.earlier?.envelope).toBe(first);
  });

  it("is not carried into another selection's attempt, and reset drops it", async () => {
    const client = new Client();
    client.answer = new AdviceApiError(503, "UNAVAILABLE");
    const seen = { latest: { phase: "idle" } as ComputePhase };
    render(
      <Harness
        client={client}
        onState={(state) => {
          seen.latest = state;
        }}
      />,
    );
    await act(async () => screen.getByText("read").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("done");

    await act(async () => screen.getByText("go-other").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("failed");
    expect(screen.getByTestId("earlier")).toHaveTextContent("none");

    // The first selection's answer, refused again: the refusal carries it, reset drops it.
    await act(async () => screen.getByText("reset").click());
    await act(async () => screen.getByText("read").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("done");
    await act(async () => screen.getByText("go").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("failed");
    expect(screen.getByTestId("earlier")).toHaveTextContent("1");
    await act(async () => screen.getByText("reset").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("idle");
    expect(screen.getByTestId("earlier")).toHaveTextContent("none");
  });

  it("is replaced by the next answer, not kept beside it", async () => {
    const client = new Client();
    client.answer = {
      kind: "advice",
      envelope: mockEntryAdviceEnvelope(REQUEST.entryId, REQUEST.strategy, REQUEST.window),
      source: "api-cache",
    };
    const seen = { latest: { phase: "idle" } as ComputePhase };
    render(
      <Harness
        client={client}
        onState={(state) => {
          seen.latest = state;
        }}
      />,
    );
    await act(async () => screen.getByText("read").click());
    await act(async () => screen.getByText("go").click());
    expect(screen.getByTestId("phase")).toHaveTextContent("done");
    expect(screen.getByTestId("earlier")).toHaveTextContent("none");
  });
});

describe("one press is one request", () => {
  it("a second press for the same selection before the first is answered sends nothing", async () => {
    const client = new Client();
    let release!: (value: AdviceRequestResult) => void;
    client.requestAdvice = async (request) => {
      client.posts.push(request);
      return new Promise((resolve) => {
        release = resolve;
      });
    };
    const seen = { latest: { phase: "idle" } as ComputePhase };
    render(
      <Harness
        client={client}
        onState={(state) => {
          seen.latest = state;
        }}
      />,
    );
    await act(async () => {
      screen.getByText("go").click();
      screen.getByText("go").click();
    });
    await act(async () => screen.getByText("go").click());
    expect(client.posts).toHaveLength(1);

    // Answered: the next press is a new request.
    await act(async () =>
      release({
        kind: "advice",
        envelope: mockEntryAdviceEnvelope(REQUEST.entryId, REQUEST.strategy, REQUEST.window),
        source: "api-cache",
      }),
    );
    expect(screen.getByTestId("phase")).toHaveTextContent("done");
    await act(async () => screen.getByText("go").click());
    expect(client.posts).toHaveLength(2);
  });

  it("a press for another selection while one is in flight is its own request", async () => {
    const client = new Client();
    client.requestAdvice = async (request) => {
      client.posts.push(request);
      return new Promise(() => {});
    };
    const seen = { latest: { phase: "idle" } as ComputePhase };
    render(
      <Harness
        client={client}
        onState={(state) => {
          seen.latest = state;
        }}
      />,
    );
    await act(async () => screen.getByText("go").click());
    await act(async () => screen.getByText("go-other").click());
    expect(client.posts.map((request) => request.window)).toEqual([1, 3]);
  });
});
