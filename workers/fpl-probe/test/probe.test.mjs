// The FPL probe's rules, run with node --test (no Cloudflare account, no network).
//
// probe.js is pure and is tested directly. index.js is exercised through its two handlers
// with an in-memory KV and a stubbed fetch, because what it stores, under which key and for
// how long, and what it refuses to answer are the parts a reader of the record relies on.

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { describe, it } from "node:test";

import worker from "../src/index.js";
import {
  EVENT_STATUS_URL,
  HEAD_CHARACTERS,
  LAST_NOW_KEY,
  NOW_PATH,
  PROBE_TIMEOUT_MS,
  RECORD_TTL_SECONDS,
  RESULTS_PATH,
  STANDINGS_URL,
  TARGETS,
  USER_AGENT,
  metadataFor,
  nowGate,
  recordFrom,
  recordKey,
  routeFor,
  summarize,
} from "../src/probe.js";

const REPOSITORY = new URL("../../../", import.meta.url);
const SITE = "https://squadopt.mymandev.com";

function memoryKv({ pageSize = 1000 } = {}) {
  const entries = new Map();
  return {
    entries,
    async get(key, type) {
      const entry = entries.get(key);
      if (entry === undefined) return null;
      return type === "json" ? JSON.parse(entry.value) : entry.value;
    },
    async put(key, value, options = {}) {
      entries.set(key, { value, metadata: options.metadata, expirationTtl: options.expirationTtl });
    },
    async list({ prefix = "", cursor } = {}) {
      const names = [...entries.keys()].filter((name) => name.startsWith(prefix)).sort();
      const start = cursor === undefined ? 0 : Number(cursor);
      const end = Math.min(names.length, start + pageSize);
      const keys = names.slice(start, end).map((name) => {
        const metadata = entries.get(name).metadata;
        return metadata === undefined ? { name } : { name, metadata };
      });
      const complete = end >= names.length;
      return { keys, list_complete: complete, ...(complete ? {} : { cursor: String(end) }) };
    },
  };
}

function fplAnswers({ standings }) {
  return async (input) => {
    const url = String(input);
    if (url.includes("/cdn-cgi/trace")) {
      return new Response("fl=1\nh=www.cloudflare.com\ncolo=LHR\nhttp=http/1.1\n");
    }
    if (url === EVENT_STATUS_URL) {
      return Response.json({ status: [], leagues: "Updated" });
    }
    if (url === STANDINGS_URL) return standings();
    throw new Error(`unexpected request to ${url}`);
  };
}

function record(at, status, json = status === 200) {
  return {
    at,
    trigger: "cron",
    target: STANDINGS_URL,
    status,
    ms: 120,
    bytes: 10,
    content_type: json ? "application/json" : "text/html",
    json,
    head: json ? null : "<html>",
    colo: "LHR",
    error: null,
  };
}

function hoursAfter(start, hours) {
  return new Date(Date.parse(start) + hours * 3_600_000).toISOString();
}

describe("a record of one answer", () => {
  it("keeps a 200 JSON answer's size and nothing of its body", () => {
    const body = JSON.stringify({ standings: { results: [{ entry_name: "PRIVATE-MARKER" }] } });
    const result = recordFrom({
      at: "2026-10-05T12:00:00.000Z",
      trigger: "cron",
      target: STANDINGS_URL,
      colo: "LHR",
      ms: 183.4,
      status: 200,
      contentType: "application/json",
      body: new TextEncoder().encode(body),
    });

    assert.deepEqual(result, {
      at: "2026-10-05T12:00:00.000Z",
      trigger: "cron",
      target: STANDINGS_URL,
      status: 200,
      ms: 183,
      bytes: body.length,
      content_type: "application/json",
      json: true,
      head: null,
      colo: "LHR",
      error: null,
    });
    assert.ok(!JSON.stringify(result).includes("PRIVATE-MARKER"));
  });

  it("keeps only a 120 character head of a 403 HTML answer", () => {
    const page =
      "<!DOCTYPE html>\n<html>\n  <head><title>Access denied</title></head>\n" +
      `  <body>${"blocked ".repeat(40)}TAIL-MARKER</body>\n</html>\n`;
    const result = recordFrom({
      at: "2026-10-05T12:00:00.000Z",
      trigger: "now",
      target: STANDINGS_URL,
      colo: "AMS",
      ms: 95,
      status: 403,
      contentType: "text/html; charset=UTF-8",
      body: page,
    });

    assert.equal(result.status, 403);
    assert.equal(result.json, false);
    assert.equal(result.bytes, new TextEncoder().encode(page).byteLength);
    assert.equal(result.content_type, "text/html; charset=UTF-8");
    assert.equal(result.error, null);
    assert.equal(result.head.length, HEAD_CHARACTERS);
    assert.ok(result.head.startsWith("<!DOCTYPE html> <html> <head><title>Access denied</title>"));
    assert.ok(!result.head.includes("\n"));
    assert.ok(!JSON.stringify(result).includes("TAIL-MARKER"));
    assert.notEqual(metadataFor(result), null, "a 403 record fits in KV metadata");
  });

  it("records a timeout as no answer at all", () => {
    const result = recordFrom({
      at: "2026-10-05T12:00:00.000Z",
      trigger: "cron",
      target: EVENT_STATUS_URL,
      colo: null,
      ms: PROBE_TIMEOUT_MS + 3,
      error: new DOMException("The operation was aborted due to timeout", "TimeoutError"),
    });

    assert.deepEqual(result, {
      at: "2026-10-05T12:00:00.000Z",
      trigger: "cron",
      target: EVENT_STATUS_URL,
      status: null,
      ms: PROBE_TIMEOUT_MS + 3,
      bytes: null,
      content_type: null,
      json: false,
      head: null,
      colo: null,
      error: `timeout after ${PROBE_TIMEOUT_MS} ms`,
    });
  });

  it("names any other network failure briefly", () => {
    const result = recordFrom({
      at: "2026-10-05T12:00:00.000Z",
      target: EVENT_STATUS_URL,
      ms: 4,
      error: new TypeError(`fetch failed ${"x".repeat(400)}`),
    });

    assert.equal(result.status, null);
    assert.ok(result.error.startsWith("TypeError: fetch failed"));
    assert.ok(result.error.length <= 160);
  });

  it("drops the metadata copy rather than exceed KV's limit", () => {
    const huge = { ...record("2026-10-05T12:00:00.000Z", 403, false), error: "e".repeat(2000) };
    assert.equal(metadataFor(huge), null);
  });
});

describe("the summary", () => {
  it("finds the longest run of failures and when it began and ended", () => {
    const start = "2026-10-05T00:00:00.000Z";
    const statuses = [200, 403, 403, 200, 403, 403, 403, 200, 429];
    const records = statuses.map((status, index) => record(hoursAfter(start, index / 2), status));
    records.push({ ...record(hoursAfter(start, 5), null, false), error: "timeout after 10000 ms" });

    const summary = summarize(records.reverse());
    const standings = summary.targets.find((entry) => entry.target === STANDINGS_URL);

    assert.equal(summary.probes, 10);
    assert.equal(summary.first_at, start);
    assert.equal(summary.last_at, hoursAfter(start, 5));
    assert.equal(standings.probes, 10);
    assert.equal(standings.served, 3);
    assert.deepEqual(standings.by_status, { 200: 3, 403: 5, 429: 1, timeout: 1 });
    assert.deepEqual(standings.longest_failure_run, {
      length: 3,
      from: hoursAfter(start, 2),
      to: hoursAfter(start, 3),
    });
    assert.equal(standings.longest_gap_minutes, 60);
    const events = summary.targets.find((entry) => entry.target === EVENT_STATUS_URL);
    assert.equal(events.probes, 0);
    assert.equal(summary.verdict.outcome, "pending");
  });

  it("applies the verdict rule only once the standings span 72 hours", () => {
    const start = "2026-10-05T00:00:00.000Z";
    // 145 half-hourly probes span exactly 72 hours; 144 span 71.5.
    const served = Array.from({ length: 145 }, (_, index) =>
      record(hoursAfter(start, index / 2), 200),
    );
    assert.equal(summarize(served).verdict.outcome, "served");
    assert.equal(summarize(served.slice(0, 144)).verdict.outcome, "pending");

    const refused = served.map((entry, index) =>
      index % 10 === 0 ? record(entry.at, 403) : entry,
    );
    const verdict = summarize(refused).verdict;
    assert.equal(verdict.standings_served, 130);
    assert.equal(verdict.outcome, "not served");
    assert.equal(verdict.span_hours, 72);
  });
});

describe("the route guard", () => {
  it("answers GET on exactly the two probe paths", () => {
    assert.equal(routeFor("GET", RESULTS_PATH), "results");
    assert.equal(routeFor("GET", NOW_PATH), "now");
    for (const method of ["POST", "PUT", "DELETE", "HEAD", "OPTIONS", "PATCH"]) {
      assert.equal(routeFor(method, RESULTS_PATH), null, method);
      assert.equal(routeFor(method, NOW_PATH), null, method);
    }
    for (const path of [
      "/",
      "/api/v1/fpl-probe/",
      "/api/v1/fpl-probe/now/",
      "/api/v1/fpl-probe/now/x",
      "/api/v1/fpl-probex",
      "/api/v1/fpl/leagues-classic/352490/standings/",
      "/API/V1/FPL-PROBE",
    ]) {
      assert.equal(routeFor("GET", path), null, path);
    }
  });

  it("answers every other path and method with a 404 JSON and asks FPL nothing", async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => {
      throw new Error("no request may leave");
    });
    const env = { PROBE: memoryKv() };
    for (const [method, path] of [
      ["POST", RESULTS_PATH],
      ["HEAD", NOW_PATH],
      ["GET", "/api/v1/fpl-probe/now/extra"],
      ["GET", "/api/v1/fpl-probe-other"],
    ]) {
      const response = await worker.fetch(new Request(`${SITE}${path}`, { method }), env);
      assert.equal(response.status, 404, `${method} ${path}`);
      assert.equal(response.headers.get("cache-control"), "no-store");
      if (method !== "HEAD") assert.deepEqual(await response.json(), { error: "not_found" });
    }
    assert.equal(fetch.mock.callCount(), 0);
    assert.equal(env.PROBE.entries.size, 0);
  });

  it("is deployed on exactly the probe's paths of the site's host", async () => {
    const config = await readFile(new URL("../wrangler.toml", import.meta.url), "utf8");
    const patterns = [...config.matchAll(/pattern\s*=\s*"([^"]*)"/g)].map((match) => match[1]);
    assert.deepEqual(patterns, ["squadopt.mymandev.com/api/v1/fpl-probe*"]);
    assert.match(config, /zone_name\s*=\s*"mymandev\.com"/);
    assert.match(config, /^workers_dev = false$/m);
    assert.match(config, /^crons = \["\*\/30 \* \* \* \*"\]$/m);
    // The committed file never carries an account's namespace id; the workflow fills it in.
    assert.match(config, /^id = "FILLED_IN_BY_THE_DEPLOY_WORKFLOW"$/m);
  });
});

describe("the worker", () => {
  it("sends the capture's own user agent", async () => {
    const capture = await readFile(
      new URL("src/squadopt/platform/fpl_capture.py", REPOSITORY),
      "utf8",
    );
    const declared = /^USER_AGENT = "([^"]+)"$/m.exec(capture);
    assert.ok(declared, "fpl_capture.py no longer declares USER_AGENT on one line");
    assert.equal(USER_AGENT, declared[1]);
  });

  it("probes every target once per scheduled run and stores each record for 14 days", async (t) => {
    const fetch = t.mock.method(
      globalThis,
      "fetch",
      fplAnswers({ standings: () => new Response("<html>denied</html>", { status: 403 }) }),
    );
    const env = { PROBE: memoryKv() };

    await worker.scheduled({ cron: "*/30 * * * *", scheduledTime: Date.now() }, env);

    const probes = fetch.mock.calls.filter((call) => TARGETS.includes(String(call.arguments[0])));
    assert.deepEqual(
      probes.map((call) => String(call.arguments[0])),
      TARGETS,
    );
    for (const call of fetch.mock.calls) {
      const init = call.arguments[1];
      assert.equal(new Headers(init.headers).get("user-agent"), USER_AGENT);
      assert.deepEqual(init.cf, { cacheTtl: 0 });
      assert.ok(init.signal instanceof AbortSignal);
    }

    const keys = [...env.PROBE.entries.keys()].sort();
    assert.equal(keys.length, 2);
    assert.match(keys[0], /^r:\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z:0$/);
    assert.equal(keys[1], keys[0].replace(/:0$/, ":1"));
    for (const [index, key] of keys.entries()) {
      const entry = env.PROBE.entries.get(key);
      assert.equal(entry.expirationTtl, RECORD_TTL_SECONDS);
      assert.deepEqual(entry.metadata, JSON.parse(entry.value));
      assert.equal(entry.metadata.target, TARGETS[index]);
      assert.equal(entry.metadata.trigger, "cron");
      assert.equal(entry.metadata.colo, "LHR");
    }
    assert.equal(env.PROBE.entries.get(keys[1]).metadata.status, 403);
    assert.equal(env.PROBE.entries.get(keys[1]).metadata.head, "<html>denied</html>");
  });

  it("returns every stored record in time order with the summary, never cached", async () => {
    const env = { PROBE: memoryKv({ pageSize: 2 }) };
    const stored = [
      ["2026-10-05T11:30:00.000Z", 1, record("2026-10-05T11:30:01.000Z", 200)],
      ["2026-10-05T11:00:00.000Z", 1, record("2026-10-05T11:00:01.000Z", 403)],
      ["2026-10-05T12:00:00.000Z", 1, record("2026-10-05T12:00:01.000Z", 200)],
    ];
    for (const [runAt, index, entry] of stored) {
      await env.PROBE.put(recordKey(runAt, index), JSON.stringify(entry), {
        metadata: entry,
      });
    }
    // A record whose metadata did not fit is read from its value.
    const late = record("2026-10-05T12:30:01.000Z", 200);
    await env.PROBE.put(recordKey("2026-10-05T12:30:00.000Z", 1), JSON.stringify(late));
    await env.PROBE.put(LAST_NOW_KEY, "0");

    const response = await worker.fetch(new Request(`${SITE}${RESULTS_PATH}`), env);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.match(response.headers.get("content-type"), /^application\/json/);
    const body = await response.json();
    assert.deepEqual(
      body.records.map((entry) => entry.at),
      [
        "2026-10-05T11:00:01.000Z",
        "2026-10-05T11:30:01.000Z",
        "2026-10-05T12:00:01.000Z",
        "2026-10-05T12:30:01.000Z",
      ],
    );
    assert.equal(body.summary.probes, 4);
    assert.equal(body.summary.verdict.standings_served, 3);
  });

  it("runs the live probe at most once a minute for everyone", async (t) => {
    const standings = () => Response.json({ standings: { results: ["PRIVATE-MARKER"] } });
    const fetch = t.mock.method(globalThis, "fetch", fplAnswers({ standings }));
    const env = { PROBE: memoryKv() };

    const first = await worker.fetch(new Request(`${SITE}${NOW_PATH}`), env);
    assert.equal(first.status, 200);
    assert.equal(first.headers.get("cache-control"), "no-store");
    const text = await first.text();
    assert.ok(!text.includes("PRIVATE-MARKER"), "a caller never receives FPL's body");
    const body = JSON.parse(text);
    assert.equal(body.stored, true);
    assert.deepEqual(
      body.records.map((entry) => [entry.target, entry.status, entry.json, entry.trigger]),
      [
        [EVENT_STATUS_URL, 200, true, "now"],
        [STANDINGS_URL, 200, true, "now"],
      ],
    );
    assert.equal(fetch.mock.callCount(), 2, "a live probe needs no trace; the request names it");
    assert.equal([...env.PROBE.entries.keys()].filter((key) => key.startsWith("r:")).length, 2);

    const second = await worker.fetch(new Request(`${SITE}${NOW_PATH}`), env);
    assert.equal(second.status, 429);
    assert.equal(second.headers.get("cache-control"), "no-store");
    const refusal = await second.json();
    assert.equal(refusal.error, "too_many_requests");
    assert.equal(second.headers.get("retry-after"), String(refusal.retry_after_seconds));
    assert.equal(fetch.mock.callCount(), 2, "a refused caller sends nothing to FPL");
  });

  it("refuses the live probe when it cannot record that it ran", async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => {
      throw new Error("no request may leave");
    });
    const kv = memoryKv();
    kv.put = async () => {
      throw new Error("KV put() limit exceeded for the day.");
    };

    const response = await worker.fetch(new Request(`${SITE}${NOW_PATH}`), { PROBE: kv });
    assert.equal(response.status, 503);
    assert.equal((await response.json()).error, "unavailable");
    assert.equal(fetch.mock.callCount(), 0);
  });
});

describe("the live probe gate", () => {
  it("opens with no stored time, after a minute, and not before", () => {
    const now = Date.parse("2026-10-05T12:00:00.000Z");
    assert.deepEqual(nowGate(null, now), { allowed: true, retryAfterSeconds: 0 });
    assert.deepEqual(nowGate("not a time", now), { allowed: true, retryAfterSeconds: 0 });
    assert.deepEqual(nowGate(String(now - 60_000), now), { allowed: true, retryAfterSeconds: 0 });
    assert.deepEqual(nowGate(String(now - 59_001), now), { allowed: false, retryAfterSeconds: 1 });
    assert.deepEqual(nowGate(String(now - 1_000), now), { allowed: false, retryAfterSeconds: 59 });
    assert.deepEqual(nowGate(String(now + 5_000), now), { allowed: false, retryAfterSeconds: 60 });
  });
});
