import { afterEach, describe, expect, it, vi } from "vitest";
import developSchema from "../../../../../tests/fixtures/llmopt_develop_prompt_schema.json";

import { requestsCarrying, sentRequests, watchKeyLeaks } from "../../../testSupport/keyLeaks";
import { EMPTY_DRAFT, intentRefusal } from "./intent";
import { ownKeyIntentSource, type IntentRequest } from "./intentSource";
import { clearOwnKey, setOwnKey } from "./ownKey";

const ORIGIN = "https://advice.example";
const PLAYERS = [{ id: 1, name: "Held One", team: "Arsenal" }];

afterEach(() => {
  clearOwnKey();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
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
const DATA = "a".repeat(64);
const PLAN = "1".repeat(64);
const planContext: NonNullable<IntentRequest["planContext"]> = {
  data_id: DATA,
  kind: "server",
  selected_plan_id: PLAN,
  plans: [
    {
      plan_id: PLAN,
      data_id: DATA,
      weeks: [
        { week: 1, transfers_in: [], transfers_out: [], chip: null, captain: 1, players: [1] },
      ],
    },
  ],
};

/** The backend's two keyless routes and the member's provider, as one fetch. */
function ownKeyFetch(
  check: () => Response = () => new Response(JSON.stringify({ status: "draft", draft: DRAFT })),
  prompt: (body: Record<string, unknown>) => Response = () => Response.json(CALL),
) {
  const fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url === `${ORIGIN}/api/v1/llmopt/prompt`) return prompt(JSON.parse(init!.body as string));
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
  it("uses the develop provider schema exactly once when an open session encounters a confirmed rollback", async () => {
    setOwnKey({ provider: "openai", model: "gpt-5-mini", key: KEY });
    const confirmCatalogueRollback = vi.fn(async () => true);
    const fetch = ownKeyFetch(undefined, (body) =>
      body.plan_context
        ? Response.json({ error: { code: "VALIDATION_FAILED" } }, { status: 422 })
        : Response.json({ ...CALL, schema: developSchema }),
    );
    const result = await ownKeyIntentSource(ORIGIN).interpret(
      { ...REQUEST, planContext, confirmCatalogueRollback },
      new AbortController().signal,
    );
    expect(result).toEqual({ status: "draft", draft: DRAFT });
    expect(confirmCatalogueRollback).toHaveBeenCalledOnce();
    const requests = sentRequests(fetch);
    expect(requests.map((r) => r.url)).toEqual([
      `${ORIGIN}/api/v1/llmopt/prompt`,
      `${ORIGIN}/api/v1/llmopt/prompt`,
      PROVIDER,
      `${ORIGIN}/api/v1/llmopt/check`,
    ]);
    const first = JSON.parse(requests[0]!.body);
    const second = JSON.parse(requests[1]!.body);
    expect(first).toEqual({ ...second, plan_context: planContext });
    expect(second).not.toHaveProperty("plan_context");
    const provider = JSON.parse(requests[2]!.body);
    expect(provider.response_format.json_schema.schema).toEqual(developSchema);
    expect(JSON.stringify(provider.messages)).not.toContain(DATA);
    expect(JSON.parse(requests[3]!.body).request).toEqual(second);
  });
  it("keeps a catalogue validation refusal when the same master is still enabled", async () => {
    const confirmCatalogueRollback = vi.fn(async () => false);
    const fetch = ownKeyFetch(undefined, () =>
      Response.json({ error: { code: "VALIDATION_FAILED" } }, { status: 422 }),
    );
    await expect(
      ownKeyIntentSource(ORIGIN).interpret(
        { ...REQUEST, planContext, confirmCatalogueRollback },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    expect(confirmCatalogueRollback).toHaveBeenCalledOnce();
    expect(sentRequests(fetch).map((r) => r.url)).toEqual([`${ORIGIN}/api/v1/llmopt/prompt`]);
  });
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
  it("never resends a provider reply or a refused check after a catalogue prompt succeeded", async () => {
    setOwnKey({ provider: "openai", model: "gpt-5-mini", key: KEY });
    const confirmCatalogueRollback = vi.fn(async () => true);
    const fetch = ownKeyFetch(() =>
      Response.json({ error: { code: "VALIDATION_FAILED" } }, { status: 422 }),
    );
    await expect(
      ownKeyIntentSource(ORIGIN).interpret(
        { ...REQUEST, planContext, confirmCatalogueRollback },
        new AbortController().signal,
      ),
    ).rejects.toMatchObject({ code: "VALIDATION_FAILED" });
    expect(confirmCatalogueRollback).not.toHaveBeenCalled();
    expect(sentRequests(fetch).map((r) => r.url)).toEqual([
      `${ORIGIN}/api/v1/llmopt/prompt`,
      PROVIDER,
      `${ORIGIN}/api/v1/llmopt/check`,
    ]);
  });

  it("reads the check's REPLY_REFUSED as the model giving no readable answer", async () => {
    setOwnKey({ provider: "openai", model: "gpt-5-mini", key: KEY });
    ownKeyFetch(
      () =>
        new Response(JSON.stringify({ error: { code: "REPLY_REFUSED", message: "operator" } }), {
          status: 422,
        }),
    );
    const refusal = ownKeyIntentSource(ORIGIN).interpret(REQUEST, new AbortController().signal);
    await expect(refusal).rejects.toMatchObject({ code: "REPLY_REFUSED" });
    await refusal.catch((error: unknown) => expect(intentRefusal(error)).toBe("replyInvalid"));
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
