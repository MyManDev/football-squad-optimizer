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
import { sameAdviceRequest, useAdviceJob, type ComputePhase } from "./useAdviceJob";
import { AdviceResponseError } from "./adviceResponse";

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

function Harness({
  client,
  allowBaseline = true,
}: {
  client: AdviceClient;
  allowBaseline?: boolean;
}) {
  const { state, compute } = useAdviceJob(client, allowBaseline);
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
