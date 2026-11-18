import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it } from "vitest";
import { vi } from "vitest";

import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { LeagueDataMissing } from "../data";
import {
  FallbackAdviceClient,
  HttpAdviceClient,
  StaticOnlyAdviceClient,
  type AdviceRequest,
} from "./adviceClient";
import { recallJob } from "./adviceJobStore";
import { ANSWER_MISMATCH, ANSWER_UNREADABLE, useAdviceJob } from "./useAdviceJob";

const request: AdviceRequest = { leagueId: 352490, entryId: 101, strategy: "saf-puan", window: 1 };

beforeEach(() => {
  sessionStorage.clear();
  vi.useFakeTimers();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status });
}

it.each(["immediate", "completed", "corrupt-poll"] as const)(
  "keeps the response failure after a %s response passes through the real fallback client",
  async (stage) => {
    const wrongMember = mockEntryAdviceEnvelope(999, "saf-puan", 1);
    const client = new FallbackAdviceClient(
      new HttpAdviceClient("https://api.example", async (url, init) => {
        if (init?.method === "POST")
          return stage === "immediate"
            ? json(wrongMember)
            : json({ job_id: "response-test", status: "queued" }, 202);
        if (String(url).includes("/advice-jobs/"))
          return stage === "corrupt-poll"
            ? new Response("<html>", { status: 200 })
            : json({ job_id: "response-test", status: "completed" });
        return json(wrongMember);
      }),
      new StaticOnlyAdviceClient(async () => {
        throw new LeagueDataMissing("unpublished-plan");
      }),
    );
    const { result } = renderHook(() => useAdviceJob(client, false));
    await act(async () => result.current.compute(request));
    if (stage !== "immediate") {
      expect(result.current.state.phase).toBe("waiting");
      expect(recallJob(request)?.jobId).toBe("response-test");
      await act(async () => vi.advanceTimersByTimeAsync(2000));
      expect(recallJob(request)).toBeNull();
    }
    expect(result.current.state).toMatchObject({
      phase: "failed",
      reason: stage === "corrupt-poll" ? ANSWER_UNREADABLE : ANSWER_MISMATCH,
    });
  },
);
