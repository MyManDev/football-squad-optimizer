/** The boundary's whole contract: empty origin is today's site; a dead backend degrades. */

import { describe, expect, it } from "vitest";

import { mockEntryAdviceEnvelope } from "../../../fixtures/league";
import { LeagueDataMissing } from "../data";
import {
  createAdviceClient,
  FallbackAdviceClient,
  HttpAdviceClient,
  StaticOnlyAdviceClient,
  type AdviceRequest,
} from "./adviceClient";

const REQUEST: AdviceRequest = {
  leagueId: 352490,
  entryId: 101,
  strategy: "saf-puan",
  window: 1,
};

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("createAdviceClient", () => {
  it("an empty origin (the default) is the static client — today's site", () => {
    expect(createAdviceClient("")).toBeInstanceOf(StaticOnlyAdviceClient);
  });

  it("a configured origin wraps HTTP in the fallback rule", () => {
    expect(createAdviceClient("https://api.example")).toBeInstanceOf(FallbackAdviceClient);
  });
});

function missingLoader(): never {
  // What data.ts raises for a document the producer never published.
  throw new LeagueDataMissing("advice/101/saf-puan/5.json");
}

describe("StaticOnlyAdviceClient", () => {
  it("serves the published tree and reports an uncomputed combination honestly", async () => {
    const client = new StaticOnlyAdviceClient();
    const hit = await client.readAdvice(REQUEST);
    expect(hit.kind).toBe("advice");
    if (hit.kind === "advice") {
      expect(hit.source).toBe("static");
      expect(hit.envelope.payload.entry_id).toBe(101);
    }
    const missing = new StaticOnlyAdviceClient(async () => missingLoader());
    const miss = await missing.readAdvice({ ...REQUEST, window: 5 });
    expect(miss.kind).toBe("not-computed");
  });

  it("cannot compute: requestAdvice degrades to the published answer or unavailable", async () => {
    const client = new StaticOnlyAdviceClient();
    const hit = await client.requestAdvice(REQUEST);
    expect(hit.kind).toBe("advice");
    const missing = new StaticOnlyAdviceClient(async () => missingLoader());
    const miss = await missing.requestAdvice({ ...REQUEST, window: 5 });
    expect(miss.kind).toBe("unavailable");
  });
});

describe("HttpAdviceClient", () => {
  it("reads a cache hit and carries the rival in the query", async () => {
    const calls: string[] = [];
    const envelope = mockEntryAdviceEnvelope(101, "saf-puan", 1);
    const client = new HttpAdviceClient("https://api.example/", async (url) => {
      calls.push(url);
      return jsonResponse(200, envelope);
    });

    const result = await client.readAdvice({ ...REQUEST, rivalEntryId: 202 });

    expect(result.kind).toBe("advice");
    if (result.kind === "advice") expect(result.source).toBe("api-cache");
    expect(calls[0]).toBe(
      "https://api.example/api/v1/leagues/352490/entries/101/advice?strategy=saf-puan&window=1&rival=202",
    );
  });

  it("404 means not computed; 202 means a job", async () => {
    const notComputed = new HttpAdviceClient("https://api.example", async () =>
      jsonResponse(404, { code: "NOT_FOUND" }),
    );
    expect((await notComputed.readAdvice(REQUEST)).kind).toBe("not-computed");

    const queued = new HttpAdviceClient("https://api.example", async () =>
      jsonResponse(202, { job_id: "job-0001" }),
    );
    const result = await queued.requestAdvice(REQUEST);
    expect(result).toEqual({ kind: "job", jobId: "job-0001" });
  });
});

describe("FallbackAdviceClient", () => {
  it("a dead backend degrades to the static tree and says so", async () => {
    const dead = new HttpAdviceClient("https://api.example", async () => {
      throw new TypeError("fetch failed");
    });
    const client = new FallbackAdviceClient(dead, new StaticOnlyAdviceClient());

    const read = await client.readAdvice(REQUEST);
    expect(read.kind).toBe("advice");
    if (read.kind === "advice") expect(read.source).toBe("static-fallback");

    const requested = await client.requestAdvice(REQUEST);
    expect(requested.kind).toBe("advice");
    if (requested.kind === "advice") expect(requested.source).toBe("static-fallback");
  });

  it("a healthy backend's cache hit wins; its honest 404 still lets the baseline answer", async () => {
    const envelope = mockEntryAdviceEnvelope(101, "saf-puan", 1);
    const healthy = new HttpAdviceClient("https://api.example", async () =>
      jsonResponse(200, envelope),
    );
    const client = new FallbackAdviceClient(healthy, new StaticOnlyAdviceClient());
    const hit = await client.readAdvice(REQUEST);
    if (hit.kind === "advice") expect(hit.source).toBe("api-cache");

    const empty = new HttpAdviceClient("https://api.example", async () =>
      jsonResponse(404, { code: "NOT_FOUND" }),
    );
    const emptyClient = new FallbackAdviceClient(empty, new StaticOnlyAdviceClient());
    const baseline = await emptyClient.readAdvice(REQUEST);
    expect(baseline.kind).toBe("advice");
    if (baseline.kind === "advice") expect(baseline.source).toBe("static");
  });
});
