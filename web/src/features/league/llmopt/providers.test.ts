import { afterEach, describe, expect, it, vi } from "vitest";

import { IntentError, intentRefusal } from "./intent";
import type { OwnKeyProvider, ProviderCredential } from "./ownKey";
import {
  PROVIDERS,
  callProvider,
  checkedProviderCall,
  providerReply,
  providerRequest,
  retryAfterSeconds,
  type ProviderCall,
} from "./providers";

const KEY = "sk-test-provider-0001";
const SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["status"],
  properties: { status: { type: "string" } },
};
const CALL: ProviderCall = {
  system: "Read the member's instructions.",
  user: '{"message":"No hits."}',
  schema: SCHEMA,
  schema_name: "llmopt_intent",
  max_output_tokens: 1200,
};
const ANSWER = '{"status":"draft"}';

function credential(provider: OwnKeyProvider, extra: Partial<ProviderCredential> = {}) {
  return { provider, model: "some-model", key: KEY, ...extra } satisfies ProviderCredential;
}

function chatReply(content: unknown, finish: unknown = "stop", refusal: unknown = null) {
  return { choices: [{ finish_reason: finish, message: { role: "assistant", content, refusal } }] };
}

afterEach(() => vi.unstubAllGlobals());

describe("the provider request", () => {
  it.each([
    ["openai", "https://api.openai.com/v1/chat/completions", "max_completion_tokens"],
    [
      "gemini",
      "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
      "max_completion_tokens",
    ],
    ["openrouter", "https://openrouter.ai/api/v1/chat/completions", "max_tokens"],
    ["mistral", "https://api.mistral.ai/v1/chat/completions", "max_tokens"],
    ["groq", "https://api.groq.com/openai/v1/chat/completions", "max_completion_tokens"],
  ] as const)(
    "sends %s a chat completion with a strict JSON schema and a bearer key",
    (provider, url, tokens) => {
      const request = providerRequest(credential(provider), CALL);
      expect(request.url).toBe(url);
      expect(request.headers).toEqual({
        "Content-Type": "application/json",
        Authorization: `Bearer ${KEY}`,
      });
      expect(request.body).toMatchObject({
        model: "some-model",
        [tokens]: 1200,
        messages: [
          { role: "system", content: CALL.system },
          { role: "user", content: CALL.user },
        ],
        response_format: {
          type: "json_schema",
          json_schema: { name: "llmopt_intent", strict: true, schema: SCHEMA },
        },
      });
      expect(JSON.stringify(request.body)).not.toContain(KEY);
    },
  );

  it("asks OpenAI not to store the call, and OpenRouter for a route that takes the schema", () => {
    expect(providerRequest(credential("openai"), CALL).body.store).toBe(false);
    expect(providerRequest(credential("openrouter"), CALL).body.provider).toEqual({
      require_parameters: true,
    });
    expect(providerRequest(credential("gemini"), CALL).body).not.toHaveProperty("store");
  });

  it("sends DeepSeek a JSON object call with the schema in the system text", () => {
    const request = providerRequest(credential("deepseek"), CALL);
    expect(request.url).toBe("https://api.deepseek.com/chat/completions");
    expect(request.headers.Authorization).toBe(`Bearer ${KEY}`);
    expect(request.body.response_format).toEqual({ type: "json_object" });
    expect(request.body.max_tokens).toBe(1200);
    const [system] = request.body.messages as { content: string }[];
    expect(system!.content.startsWith(CALL.system)).toBe(true);
    expect(system!.content).toContain(JSON.stringify(SCHEMA));
    expect(system!.content).toMatch(/JSON/);
  });

  it("sends a local server the call at the member's loopback base, without a key when none", () => {
    const request = providerRequest(
      credential("local", { key: "", baseUrl: "http://localhost:11434/v1" }),
      CALL,
    );
    expect(request.url).toBe("http://localhost:11434/v1/chat/completions");
    expect(request.headers).toEqual({ "Content-Type": "application/json" });
    expect(request.body.response_format).toMatchObject({ type: "json_schema" });
    const keyed = providerRequest(
      credential("local", { baseUrl: "http://127.0.0.1:1234/v1" }),
      CALL,
    );
    expect(keyed.headers.Authorization).toBe(`Bearer ${KEY}`);
  });

  it("sends Anthropic one forced tool whose input schema is the result schema", () => {
    const request = providerRequest(credential("anthropic"), CALL);
    expect(request.url).toBe("https://api.anthropic.com/v1/messages");
    expect(request.headers).toEqual({
      "Content-Type": "application/json",
      "x-api-key": KEY,
      "anthropic-version": "2023-06-01",
      "anthropic-dangerous-direct-browser-access": "true",
    });
    expect(request.body).toEqual({
      model: "some-model",
      max_tokens: 1200,
      system: CALL.system,
      messages: [{ role: "user", content: CALL.user }],
      tools: [{ name: "llmopt_intent", input_schema: SCHEMA }],
      tool_choice: { type: "tool", name: "llmopt_intent" },
    });
  });

  it("lists only the hosts the site's connect-src names", () => {
    const hosts = Object.values(PROVIDERS)
      .map(({ endpoint }) => endpoint && new URL(endpoint).host)
      .filter(Boolean);
    expect(hosts.sort()).toEqual(
      [
        "api.anthropic.com",
        "api.deepseek.com",
        "api.groq.com",
        "api.mistral.ai",
        "api.openai.com",
        "generativelanguage.googleapis.com",
        "openrouter.ai",
      ].sort(),
    );
  });
});

describe("the provider reply", () => {
  it("reads the JSON text of a chat completion", () => {
    expect(providerReply("openai", CALL, chatReply(ANSWER))).toBe(ANSWER);
    expect(providerReply("local", CALL, chatReply(ANSWER, undefined))).toBe(ANSWER);
  });

  it("reads the input of Anthropic's forced tool", () => {
    const input = { status: "draft" };
    expect(
      providerReply("anthropic", CALL, {
        stop_reason: "tool_use",
        content: [
          { type: "text", text: "Here it is." },
          { type: "tool_use", id: "t1", name: "llmopt_intent", input },
        ],
      }),
    ).toEqual(input);
  });

  it.each([
    ["openai", null],
    ["openai", { choices: [] }],
    ["openai", chatReply(ANSWER, "length")],
    ["openai", chatReply(ANSWER, "stop", "I cannot help with that.")],
    ["openai", chatReply(null)],
    ["openai", chatReply("  ")],
    ["anthropic", { content: [{ type: "text", text: ANSWER }] }],
    ["anthropic", { content: [{ type: "tool_use", name: "other", input: {} }] }],
    [
      "anthropic",
      {
        stop_reason: "max_tokens",
        content: [{ type: "tool_use", name: "llmopt_intent", input: {} }],
      },
    ],
  ] as const)("refuses a %s reply without an answer: %j", (provider, value) => {
    expect(() => providerReply(provider, CALL, value)).toThrow(IntentError);
    try {
      providerReply(provider, CALL, value);
    } catch (error) {
      expect(intentRefusal(error)).toBe("invalid");
    }
  });
});

describe("a provider call", () => {
  function stubProvider(response: () => Response | Promise<Response>) {
    const fetch = vi.fn(async () => response());
    vi.stubGlobal("fetch", fetch);
    return fetch;
  }

  async function failure(provider: OwnKeyProvider = "openai"): Promise<IntentError> {
    try {
      await callProvider(credential(provider), CALL, new AbortController().signal);
    } catch (error) {
      expect(error).toBeInstanceOf(IntentError);
      expect(String(error)).not.toContain(KEY);
      expect(JSON.stringify(error)).not.toContain(KEY);
      return error as IntentError;
    }
    throw new Error("The call did not fail.");
  }

  it("posts to the provider without cookies or referrer and returns the answer", async () => {
    const fetch = stubProvider(() => new Response(JSON.stringify(chatReply(ANSWER))));
    await expect(
      callProvider(credential("groq"), CALL, new AbortController().signal),
    ).resolves.toBe(ANSWER);
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("https://api.groq.com/openai/v1/chat/completions");
    expect(init).toMatchObject({
      method: "POST",
      credentials: "omit",
      referrerPolicy: "no-referrer",
      cache: "no-store",
    });
  });

  it.each([401, 403])("reads a %i as the key refused", async (status) => {
    stubProvider(
      () =>
        new Response(JSON.stringify({ error: { message: `Incorrect API key provided: ${KEY}` } }), {
          status,
        }),
    );
    const error = await failure();
    expect(error.code).toBe("PROVIDER_KEY_REFUSED");
    expect(intentRefusal(error)).toBe("keyRefused");
  });

  it("reads Gemini's 400 for a bad key as the key refused", async () => {
    stubProvider(
      () =>
        new Response(
          JSON.stringify([
            {
              error: {
                code: 400,
                message: "API key not valid. Please pass a valid API key.",
                status: "INVALID_ARGUMENT",
                details: [{ reason: "API_KEY_INVALID" }],
              },
            },
          ]),
          { status: 400 },
        ),
    );
    expect(intentRefusal(await failure("gemini"))).toBe("keyRefused");
  });

  it.each([
    [404, { error: { message: "The model `x` does not exist", code: "model_not_found" } }],
    [400, { error: { message: "Model Not Exist", type: "invalid_request_error" } }],
    [400, { object: "error", message: "Invalid model: x", type: "invalid_model" }],
    [404, { type: "error", error: { type: "not_found_error", message: "model: x" } }],
  ])("reads a %i naming the model as the model refused", async (status, body) => {
    stubProvider(() => new Response(JSON.stringify(body), { status }));
    const error = await failure();
    expect(error.code).toBe("PROVIDER_MODEL_REFUSED");
    expect(intentRefusal(error)).toBe("modelRefused");
  });

  it("reads another 400 as the request refused", async () => {
    stubProvider(
      () => new Response(JSON.stringify({ error: { message: "Bad input." } }), { status: 400 }),
    );
    expect(intentRefusal(await failure())).toBe("unsupported");
  });

  it("reads a 429 as the provider's limit and honours Retry-After", async () => {
    stubProvider(() => new Response("{}", { status: 429, headers: { "Retry-After": "17" } }));
    const error = await failure();
    expect(error).toMatchObject({ code: "PROVIDER_RATE_LIMITED", retryAfterSeconds: 17 });
    expect(intentRefusal(error)).toBe("providerLimited");
  });

  it("reads Retry-After as seconds or as a date", () => {
    const now = Date.parse("2026-11-17T12:00:00Z");
    expect(retryAfterSeconds("30", now)).toBe(30);
    expect(retryAfterSeconds("Tue, 17 Nov 2026 12:01:00 GMT", now)).toBe(60);
    expect(retryAfterSeconds("Tue, 17 Nov 2026 11:59:00 GMT", now)).toBeNull();
    expect(retryAfterSeconds("soon", now)).toBeNull();
    expect(retryAfterSeconds(null, now)).toBeNull();
    expect(retryAfterSeconds("999999999", now)).toBe(86_400);
  });

  it("reads a 5xx as the provider not answering", async () => {
    stubProvider(() => new Response("upstream", { status: 503 }));
    expect(intentRefusal(await failure())).toBe("busy");
  });

  it("reads a network or CORS failure as the provider unreachable", async () => {
    stubProvider(() => Promise.reject(new TypeError("Failed to fetch")));
    const error = await failure();
    expect(error.code).toBe("PROVIDER_UNREACHABLE");
    expect(intentRefusal(error)).toBe("providerUnreachable");
  });

  it("reads a reply that is not JSON as an invalid reply", async () => {
    stubProvider(() => new Response("<html>"));
    expect(intentRefusal(await failure())).toBe("invalid");
  });

  it("rejects a cancelled call as cancelled", async () => {
    stubProvider(() => new Promise<Response>(() => {}));
    const controller = new AbortController();
    const call = callProvider(credential("openai"), CALL, controller.signal);
    controller.abort();
    await expect(call).rejects.toHaveProperty("name", "AbortError");
  });
});

describe("the call /prompt returns", () => {
  it("is taken when every field holds", () => {
    expect(checkedProviderCall({ ...CALL, extra: 1 })).toEqual(CALL);
  });

  it.each([
    null,
    { ...CALL, system: 1 },
    { ...CALL, schema: [] },
    { ...CALL, schema_name: "has space" },
    { ...CALL, max_output_tokens: 0 },
    { ...CALL, max_output_tokens: 1.5 },
  ])("is refused when a field does not hold: %j", (value) => {
    expect(() => checkedProviderCall(value)).toThrow("Invalid prompt");
  });
});
