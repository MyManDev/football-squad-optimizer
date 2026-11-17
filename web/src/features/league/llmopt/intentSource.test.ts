import { afterEach, describe, expect, it, vi } from "vitest";

import { requestsCarrying, sentRequests, watchKeyLeaks } from "../../../testSupport/keyLeaks";
import { EMPTY_DRAFT, IntentError, intentRefusal } from "./intent";
import { ownKeyIntentSource, serverIntentSource, type IntentRequest } from "./intentSource";
import { clearOwnKey, setOwnKey } from "./ownKey";

const ORIGIN = "https://advice.example";
const PLAYERS = [{ id: 1, name: "Held One", team: "Arsenal" }];

afterEach(() => {
  clearOwnKey();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

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

const KEY = "sk-test-own-key-round-0001";
const PROVIDER = "https://api.openai.com/v1/chat/completions";
const CALL = {
  system: "Read the member's instructions.",
  user: '{"message":"No hits."}',
  schema: { type: "object" },
  schema_name: "llmopt_intent",
  max_output_tokens: 1200,
};
const REQUEST: IntentRequest = {
  message: "No hits.",
  locale: "en",
  draft: EMPTY_DRAFT,
  players: PLAYERS,
  referenceWeeks: [1],
};
const DRAFT = { hard: [{ kind: "no_hits" }], soft: [] };

/** The backend's two keyless routes and the member's provider, as one fetch. */
function ownKeyFetch(
  check: () => Response = () => new Response(JSON.stringify({ status: "draft", draft: DRAFT })),
) {
  const fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === `${ORIGIN}/api/v1/llmopt/prompt`) return new Response(JSON.stringify(CALL));
    if (url === PROVIDER)
      return new Response(
        JSON.stringify({
          choices: [{ finish_reason: "stop", message: { content: '{"status":"draft"}' } }],
        }),
      );
    if (url === `${ORIGIN}/api/v1/llmopt/check`) {
      return check();
    }
    return new Response("{}", { status: 404 });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("ownKeyIntentSource", () => {
  it("asks the site for the call, sends it to the provider with the key, and has the site check the reply", async () => {
    setOwnKey({ provider: "openai", model: "gpt-5-mini", key: KEY });
    const fetch = ownKeyFetch();
    const answer = await ownKeyIntentSource(ORIGIN).interpret(
      REQUEST,
      new AbortController().signal,
    );
    expect(answer).toEqual({ status: "draft", draft: DRAFT });
    const [prompt, provider, check] = sentRequests(fetch);
    const body = {
      message: "No hits.",
      locale: "en",
      draft: EMPTY_DRAFT,
      players: PLAYERS,
      reference_weeks: [1],
    };
    expect(prompt!.url).toBe(`${ORIGIN}/api/v1/llmopt/prompt`);
    expect(JSON.parse(prompt!.body)).toEqual(body);
    expect(prompt!.headers).toEqual([["content-type", "application/json"]]);
    expect(provider!.url).toBe(PROVIDER);
    expect(provider!.headers).toContainEqual(["authorization", `Bearer ${KEY}`]);
    expect(JSON.parse(provider!.body)).toMatchObject({
      model: "gpt-5-mini",
      messages: [
        { role: "system", content: CALL.system },
        { role: "user", content: CALL.user },
      ],
    });
    expect(check!.url).toBe(`${ORIGIN}/api/v1/llmopt/check`);
    expect(check!.headers).toEqual([["content-type", "application/json"]]);
    expect(JSON.parse(check!.body)).toEqual({ request: body, reply: '{"status":"draft"}' });
    expect(fetch).toHaveBeenCalledTimes(3);
  });

  it("returns the check's question back to the member", async () => {
    setOwnKey({ provider: "openai", model: "gpt-5-mini", key: KEY });
    ownKeyFetch(
      () => new Response(JSON.stringify({ status: "clarification", message: "Which week?" })),
    );
    await expect(
      ownKeyIntentSource(ORIGIN).interpret(REQUEST, new AbortController().signal),
    ).resolves.toEqual({ status: "clarification", message: "Which week?" });
  });

  it("reads the check's REPLY_REFUSED as the chat not reading the request", async () => {
    setOwnKey({ provider: "openai", model: "gpt-5-mini", key: KEY });
    ownKeyFetch(
      () =>
        new Response(JSON.stringify({ error: { code: "REPLY_REFUSED", message: "operator" } }), {
          status: 422,
        }),
    );
    const refusal = ownKeyIntentSource(ORIGIN).interpret(REQUEST, new AbortController().signal);
    await expect(refusal).rejects.toMatchObject({ code: "REPLY_REFUSED" });
    await refusal.catch((error: unknown) => expect(intentRefusal(error)).toBe("invalid"));
  });

  it("calls no provider and no check when no key is held", async () => {
    const fetch = ownKeyFetch();
    await expect(
      ownKeyIntentSource(ORIGIN).interpret(REQUEST, new AbortController().signal),
    ).rejects.toThrow();
    expect(sentRequests(fetch).map(({ url }) => url)).toEqual([`${ORIGIN}/api/v1/llmopt/prompt`]);
  });

  it("puts the key in no storage, log, beacon or site request in a full round", async () => {
    const watch = watchKeyLeaks(KEY);
    try {
      setOwnKey({ provider: "openai", model: "gpt-5-mini", key: KEY });
      const fetch = ownKeyFetch();
      await ownKeyIntentSource(ORIGIN).interpret(REQUEST, new AbortController().signal);
      expect(watch.leaks()).toEqual([]);
      expect(requestsCarrying(fetch, KEY)).toEqual([PROVIDER]);
    } finally {
      watch.restore();
    }
  });
});
