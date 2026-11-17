import { afterEach, describe, expect, it, vi } from "vitest";

import { EMPTY_DRAFT, IntentError } from "./intent";
import { serverIntentSource } from "./intentSource";

const ORIGIN = "https://advice.example";
const PLAYERS = [{ id: 1, name: "Held One", team: "Arsenal" }];

afterEach(() => vi.unstubAllGlobals());

describe("serverIntentSource", () => {
  it("sends the request to the site's intent service and returns its checked draft", async () => {
    const fetch = vi.fn(
      async () =>
        new Response(
          JSON.stringify({ status: "draft", draft: { hard: [{ kind: "no_hits" }], soft: [] } }),
        ),
    );
    vi.stubGlobal("fetch", fetch);
    const answer = await serverIntentSource(ORIGIN).interpret(
      {
        message: "No hits.",
        locale: "en",
        draft: EMPTY_DRAFT,
        players: PLAYERS,
        clarification: { message: "No hits.", question: "Which week?" },
        referenceWeeks: [1],
      },
      new AbortController().signal,
    );
    expect(answer).toEqual({ status: "draft", draft: { hard: [{ kind: "no_hits" }], soft: [] } });
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe(`${ORIGIN}/api/v1/llmopt/intent`);
    expect(JSON.parse(String(init.body))).toEqual({
      message: "No hits.",
      locale: "en",
      draft: EMPTY_DRAFT,
      players: PLAYERS,
      clarification: { message: "No hits.", question: "Which week?" },
      reference_weeks: [1],
    });
  });

  it("rejects a refusal with the service's code", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response(JSON.stringify({ error: { code: "LLMOPT_DISABLED" } }), { status: 503 }),
      ),
    );
    const refusal = serverIntentSource(ORIGIN).interpret(
      { message: "No hits.", locale: "en", draft: EMPTY_DRAFT, players: PLAYERS },
      new AbortController().signal,
    );
    await expect(refusal).rejects.toBeInstanceOf(IntentError);
    await expect(refusal).rejects.toMatchObject({ code: "LLMOPT_DISABLED" });
  });
});
