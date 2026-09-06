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
import { useAdviceJob, type ComputePhase } from "./useAdviceJob";

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

function Harness({ client }: { client: AdviceClient }) {
  const { state, compute } = useAdviceJob(client);
  return (
    <div>
      <output data-testid="phase">{describePhase(state)}</output>
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

describe("useAdviceJob", () => {
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
