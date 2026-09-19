/**
 * What goes over the wire once the member's switches and the service's capabilities exist:
 * a plain request is the request it always was, a switched one names only what is on, every
 * click carries one key, a refusal keeps its code and drops its text, and a service that is
 * down is no service at all.
 */

import { describe, expect, it, vi } from "vitest";

import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceEvidenceEnvelope,
  mockEntryAdviceTop100Envelope,
} from "../../../fixtures/league";
import {
  AdviceApiError,
  FallbackAdviceClient,
  HttpAdviceClient,
  SERVICE_UNREACHABLE,
  StaticOnlyAdviceClient,
  newIdempotencyKey,
  type AdviceRequest,
} from "./adviceClient";
import { AdviceContextError, checkedAdvice } from "./adviceResponse";

const ENTRY = 35249001;
const PLAIN: AdviceRequest = { leagueId: 352490, entryId: ENTRY, strategy: "saf-puan", window: 1 };
const ROUTE = `https://api.example/api/v1/leagues/352490/entries/${ENTRY}/advice`;
const KEY_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$/; // the service's own pattern

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers });
}

function sentKey(call: { init?: RequestInit }): string | undefined {
  return (call.init?.headers as Record<string, string> | undefined)?.["Idempotency-Key"];
}

function recorder(respond: (url: string, init?: RequestInit) => Response) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const client = new HttpAdviceClient("https://api.example/", async (url, init) => {
    calls.push({ url, init });
    return respond(url, init);
  });
  return { calls, client };
}

const CAPABILITIES = {
  contract_version: "league_capabilities_v1",
  league_id: 352490,
  capture_snapshot_id: "example-post-deadline-gw02",
  season: "2026-27",
  gameweek: 2,
  strategies: {
    "fark-yarat": { windows: [1, 3, 5], requires_rival: true },
    "saf-puan": { windows: [1, 3, 5], requires_rival: false },
  },
  top100: { available: true, weights: [0, 5, 10, 20, 30, 40, 50] },
  managers_word: { available: false },
};

describe("the request on the wire", () => {
  it("sends a plain request exactly as before, switches stated off or not at all", async () => {
    for (const request of [
      PLAIN,
      { ...PLAIN, chip: null },
      { ...PLAIN, top100Weight: 0, managersWord: false },
    ]) {
      const { calls, client } = recorder(() =>
        jsonResponse(202, { job_id: "j", status: "queued" }),
      );
      await client.requestAdvice(request);
      await client.readAdvice(request).catch(() => undefined);
      expect(calls[0]!.url).toBe(`${ROUTE}?strategy=saf-puan&window=1`);
      expect(calls[0]!.init?.body).toBe(
        JSON.stringify({ strategy: "saf-puan", window: 1, rival_entry_id: null }),
      );
      expect(calls[1]!.url).toBe(`${ROUTE}?strategy=saf-puan&window=1`);
    }
  });

  it("names a switch only when it is on, in the body and in the query", async () => {
    const { calls, client } = recorder(() => jsonResponse(202, { job_id: "j", status: "queued" }));
    await client.requestAdvice({ ...PLAIN, top100Weight: 20, managersWord: true });
    await client.requestAdvice({
      ...PLAIN,
      strategy: "fark-yarat",
      window: 3,
      rivalEntryId: 7,
      top100Weight: 5,
      managersWord: false,
    });
    expect(JSON.parse(String(calls[0]!.init?.body))).toEqual({
      strategy: "saf-puan",
      window: 1,
      rival_entry_id: null,
      top100_weight: 20,
      managers_word: true,
    });
    expect(calls[0]!.url).toBe(
      `${ROUTE}?strategy=saf-puan&window=1&top100_weight=20&managers_word=true`,
    );
    expect(JSON.parse(String(calls[1]!.init?.body))).toEqual({
      strategy: "fark-yarat",
      window: 3,
      rival_entry_id: 7,
      top100_weight: 5,
    });
    expect(calls[1]!.url).toBe(`${ROUTE}?strategy=fark-yarat&window=3&rival=7&top100_weight=5`);
  });

  it("carries the click's key, and makes one the service accepts when given none", async () => {
    const { calls, client } = recorder(() => jsonResponse(202, { job_id: "j", status: "queued" }));
    await client.requestAdvice(PLAIN, { idempotencyKey: "click-1" });
    await client.requestAdvice(PLAIN);
    const keys = calls.map(sentKey);
    expect(keys[0]).toBe("click-1");
    expect(keys[1]).toMatch(KEY_PATTERN);
    expect(newIdempotencyKey()).toMatch(KEY_PATTERN);
    expect(newIdempotencyKey()).not.toBe(newIdempotencyKey());
  });

  it("asks a busy queue again with the same key, then gives up with its code", async () => {
    vi.useFakeTimers();
    try {
      let attempts = 0;
      const { calls, client } = recorder(() => {
        attempts += 1;
        return attempts < 3
          ? jsonResponse(503, { error: { code: "NOT_READY", message: "busy" } })
          : jsonResponse(202, { job_id: "job-9", status: "queued" });
      });
      const signal = new AbortController().signal;
      const accepted = client.requestAdvice(PLAIN, { signal, idempotencyKey: "click-2" });
      await vi.advanceTimersByTimeAsync(4100);
      await expect(accepted).resolves.toEqual({ kind: "job", jobId: "job-9" });
      expect(calls.map(sentKey)).toEqual(["click-2", "click-2", "click-2"]);

      const down = recorder(() =>
        jsonResponse(503, { error: { code: "QUEUE_UNAVAILABLE", message: "x" } }),
      );
      const refused = down.client.requestAdvice(PLAIN, { signal });
      const outcome = expect(refused).rejects.toMatchObject({
        status: 503,
        code: "QUEUE_UNAVAILABLE",
      });
      await vi.advanceTimersByTimeAsync(4100);
      await outcome;
      expect(down.calls).toHaveLength(3);
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("a refusal", () => {
  it.each([
    [422, "TOP100_INPUTS_UNAVAILABLE"],
    [422, "MANAGERS_WORD_UNAVAILABLE"],
    [422, "UNSUPPORTED_ADVICE_REQUEST"],
    [404, "UNKNOWN_ENTRY"],
    [409, "IDEMPOTENCY_CONFLICT"],
  ])("%i keeps the service's code %s and none of its text", async (status, code) => {
    const { client } = recorder(() =>
      jsonResponse(status, { error: { code, message: "C:\\store\\secret path" } }),
    );
    const error = await client.requestAdvice(PLAIN).catch((caught: unknown) => caught);
    expect(error).toBeInstanceOf(AdviceApiError);
    expect(error).toMatchObject({ status, code, retryAfterSeconds: null });
    expect(String((error as Error).message)).not.toContain("secret");
  });

  it("reads Retry-After when the browser may, and does without it when it may not", async () => {
    const limited = recorder(() =>
      jsonResponse(429, { error: { code: "RATE_LIMITED" } }, { "Retry-After": "60" }),
    );
    await expect(limited.client.requestAdvice(PLAIN)).rejects.toMatchObject({
      code: "RATE_LIMITED",
      retryAfterSeconds: 60,
    });
    const hidden = recorder(() => jsonResponse(429, { error: { code: "RATE_LIMITED" } }));
    await expect(hidden.client.requestAdvice(PLAIN)).rejects.toMatchObject({
      code: "RATE_LIMITED",
      retryAfterSeconds: null,
    });
  });

  it("treats a code that is not a code, or a body that is not JSON, as no code", async () => {
    const odd = recorder(() => jsonResponse(500, { error: { code: "<script>alert(1)</script>" } }));
    await expect(odd.client.readJob("job-1")).rejects.toMatchObject({ status: 500, code: null });
    const html = new HttpAdviceClient(
      "https://api.example",
      async () => new Response("<html>502</html>", { status: 502 }),
    );
    await expect(html.readJob("job-1")).rejects.toMatchObject({ status: 502, code: null });
  });

  it("keeps a failed job's error code and drops anything else in the view", async () => {
    const { client } = recorder(() =>
      jsonResponse(200, {
        contract_version: "advice_job_view_v1",
        job_id: "job-1",
        status: "failed",
        attempt: 3,
        error_code: "TOO_MANY_ATTEMPTS",
      }),
    );
    expect(await client.readJob("job-1")).toEqual({
      jobId: "job-1",
      status: "failed",
      errorCode: "TOO_MANY_ATTEMPTS",
    });
  });
});

describe("an answer held to the switches that asked for it", () => {
  const plain = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1);
  const weighted = mockEntryAdviceTop100Envelope(ENTRY, 20, false);
  const worded = mockEntryAdviceEvidenceEnvelope(ENTRY);
  const request = { ...PLAIN, season: plain.payload.season, gameweek: plain.payload.gameweek };

  it("accepts the plan solved under exactly those switches", () => {
    expect(() =>
      checkedAdvice(plain, { ...request, top100Weight: 0, managersWord: false }),
    ).not.toThrow();
    expect(() =>
      checkedAdvice(weighted, { ...request, top100Weight: 20, managersWord: false }),
    ).not.toThrow();
    expect(() =>
      checkedAdvice(worded, { ...request, top100Weight: 0, managersWord: true }),
    ).not.toThrow();
  });

  it.each([
    ["the plain plan for a setting", plain, { top100Weight: 20, managersWord: false }],
    ["another setting's plan", weighted, { top100Weight: 30, managersWord: false }],
    ["a weighted plan for the plain one", weighted, { top100Weight: 0, managersWord: false }],
    ["the plain plan for the word", plain, { top100Weight: 0, managersWord: true }],
    ["the word's plan for the plain one", worded, { top100Weight: 0, managersWord: false }],
  ])("refuses %s", (_name, envelope, switches) => {
    expect(() => checkedAdvice(envelope, { ...request, ...switches })).toThrow(AdviceContextError);
  });

  it("holds a request that states no switch to none, as a static build always has", () => {
    expect(() => checkedAdvice(weighted, request)).not.toThrow();
    expect(() => checkedAdvice(worded, request)).not.toThrow();
  });
});

describe("the static tree under a switched request", () => {
  it("never answers a switched request with the plain file", async () => {
    const loader = vi.fn(async () => mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1));
    const client = new StaticOnlyAdviceClient(loader);
    expect(await client.readAdvice({ ...PLAIN, top100Weight: 20 })).toEqual({
      kind: "not-computed",
    });
    expect(await client.requestAdvice({ ...PLAIN, managersWord: true })).toEqual({
      kind: "unavailable",
    });
    expect(loader).not.toHaveBeenCalled();
    expect((await client.readAdvice({ ...PLAIN, top100Weight: 0 })).kind).toBe("advice");
  });

  it("says why when the service is down and nothing published can stand in", async () => {
    const dead = new FallbackAdviceClient(
      new HttpAdviceClient("https://api.example", async () => {
        throw new TypeError("Failed to fetch");
      }),
      new StaticOnlyAdviceClient(async () => mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1)),
    );
    expect(await dead.requestAdvice({ ...PLAIN, top100Weight: 20 })).toEqual({
      kind: "unavailable",
      reason: SERVICE_UNREACHABLE,
    });
    expect(await dead.requestAdvice(PLAIN)).toMatchObject({
      kind: "advice",
      source: "static-fallback",
    });
    const notReady = new FallbackAdviceClient(
      new HttpAdviceClient("https://api.example", async () =>
        jsonResponse(503, { error: { code: "ADVICE_BACKEND_DISABLED" } }),
      ),
      new StaticOnlyAdviceClient(async () => mockEntryAdviceEnvelope(ENTRY, "saf-puan", 1)),
    );
    expect(await notReady.requestAdvice({ ...PLAIN, managersWord: true })).toEqual({
      kind: "unavailable",
      reason: "ADVICE_BACKEND_DISABLED",
    });
  });
});

describe("capabilities", () => {
  it("reads them from the league's route and hands the page a checked document", async () => {
    const { calls, client } = recorder(() => jsonResponse(200, CAPABILITIES));
    const capabilities = await client.readCapabilities(352490);
    expect(calls[0]!.url).toBe("https://api.example/api/v1/leagues/352490/capabilities");
    expect(calls[0]!.init?.method).toBeUndefined();
    expect(capabilities).toMatchObject({
      leagueId: 352490,
      captureSnapshotId: "example-post-deadline-gw02",
      top100Weights: [0, 5, 10, 20, 30, 40, 50],
      managersWord: false,
    });
  });

  it.each([
    ["the service is unreachable", () => Promise.reject(new TypeError("Failed to fetch"))],
    ["the service is not ready", async () => jsonResponse(503, { error: { code: "NOT_READY" } })],
    ["the league is not connected", async () => jsonResponse(404, { error: { code: "X" } })],
    ["the document is another shape", async () => jsonResponse(200, { league_id: 352490 })],
    ["the document is not JSON", async () => new Response("<html>", { status: 200 })],
  ])("is no capabilities at all when %s", async (_name, respond) => {
    const client = new FallbackAdviceClient(
      new HttpAdviceClient("https://api.example", respond),
      new StaticOnlyAdviceClient(),
    );
    await expect(client.readCapabilities(352490)).resolves.toBeNull();
  });

  it("is not something the static client can be asked", () => {
    expect("readCapabilities" in new StaticOnlyAdviceClient()).toBe(false);
  });
});
