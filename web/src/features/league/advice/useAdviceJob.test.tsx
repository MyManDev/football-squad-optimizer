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
});
