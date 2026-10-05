// The FPL probe's rules, run with node --test (no Cloudflare account, no network).
//
// probe.js is pure and is tested directly. worker.js is exercised through its two handlers
// with an in-memory KV, an in-memory cache and a stubbed fetch, because what it stores, under
// which key and for how long, and what it refuses to answer are the parts a reader of the
// record relies on. Each test builds its own handlers, so no isolate state leaks between them.

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { describe, it } from "node:test";

import entry from "../src/index.js";
import { createWorker } from "../src/worker.js";
import {
  EVENT_STATUS_URL,
  HEAD_CHARACTERS,
  MARKER_VALUE,
  NOW_DAILY_CAP,
  NOW_GATE_KEY,
  NOW_GATE_TTL_SECONDS,
  NOW_HEADER_VALUE,
  NOW_PATH,
  PROBE_HEADER,
  PROBE_TIMEOUT_MS,
  RECORD_TTL_SECONDS,
  RESULTS_PATH,
  STANDINGS_URL,
  TARGETS,
  USER_AGENT,
  VERDICT_MIN_PROBES,
  metadataFor,
  nowGate,
  probeActive,
  recordFrom,
  recordKey,
  routeFor,
  summarize,
} from "../src/probe.js";

const REPOSITORY = new URL("../../../", import.meta.url);
const SITE = "https://squadopt.mymandev.com";
const LIVE = { [PROBE_HEADER]: NOW_HEADER_VALUE };

function memoryKv({ pageSize = 1000 } = {}) {
  const entries = new Map();
  const counts = { put: 0, list: 0 };
  return {
    entries,
    counts,
    async get(key, type) {
      const entry = entries.get(key);
      if (entry === undefined) return null;
      return type === "json" ? JSON.parse(entry.value) : entry.value;
    },
    async put(key, value, options = {}) {
      counts.put += 1;
      entries.set(key, { value, metadata: options.metadata, expirationTtl: options.expirationTtl });
    },
    async list({ prefix = "", cursor } = {}) {
      counts.list += 1;
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

/** A data centre's cache as the Worker uses it: match and put by URL, nothing expires. */
function memoryCache() {
  const stored = new Map();
  return {
    stored,
    async match(request) {
      const hit = stored.get(new Request(request).url);
      return hit === undefined ? undefined : new Response(hit.text, { headers: hit.headers });
    },
    async put(request, response) {
      stored.set(new Request(request).url, {
        text: await response.text(),
        headers: Object.fromEntries(response.headers),
      });
    },
  };
}

/** An environment whose probe runs for another day. */
function probeEnv(kv = memoryKv()) {
  return { PROBE: kv, PROBE_UNTIL: new Date(Date.now() + 86_400_000).toISOString() };
}

function liveRequest(headers = LIVE) {
  return new Request(`${SITE}${NOW_PATH}`, { headers });
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

function record(at, status, json = status === 200, trigger = "cron") {
  return {
    at,
    trigger,
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
    const standings = summary.scheduled.find((entry) => entry.target === STANDINGS_URL);

    assert.equal(summary.probes, 10);
    assert.equal(summary.first_at, start);
    assert.equal(summary.last_at, hoursAfter(start, 5));
    assert.deepEqual(summary.by_trigger, { cron: 10 });
    assert.equal(standings.probes, 10);
    assert.equal(standings.served, 3);
    assert.deepEqual(standings.by_status, { 200: 3, 403: 5, 429: 1, timeout: 1 });
    assert.deepEqual(standings.longest_failure_run, {
      length: 3,
      from: hoursAfter(start, 2),
      to: hoursAfter(start, 3),
    });
    assert.equal(standings.longest_gap_minutes, 60);
    const events = summary.scheduled.find((entry) => entry.target === EVENT_STATUS_URL);
    assert.equal(events.probes, 0);
    assert.equal(summary.verdict.outcome, "pending");
  });
});

describe("the verdict", () => {
  const start = "2026-10-05T00:00:00.000Z";
  const halfHourly = (count, status = () => 200, from = 0) =>
    Array.from({ length: count }, (_, index) =>
      record(hoursAfter(start, (from + index) / 2), status(from + index)),
    );

  it("stays pending until a scheduled probe reaches the end of the first 72 hours", () => {
    // 145 half-hourly probes run from the window's start to its end, both included.
    const served = halfHourly(145);
    const verdict = summarize(served).verdict;
    assert.equal(verdict.outcome, "served");
    assert.equal(verdict.window_from, start);
    assert.equal(verdict.window_to, hoursAfter(start, 72));
    assert.equal(verdict.window_probes, 145);
    assert.equal(summarize(served.slice(0, 144)).verdict.outcome, "pending");
  });

  it("compares times unrounded: a millisecond short of 72 hours is still pending", () => {
    const short = halfHourly(144);
    short.push(record(new Date(Date.parse(hoursAfter(start, 72)) - 1).toISOString(), 200));
    assert.equal(summarize(short).verdict.outcome, "pending");
  });

  it("never moves once the window has closed, however long the probe runs on", () => {
    // 8 refusals among the first 145: 137 of 145 is below 95 percent.
    const refusals = new Set([3, 20, 40, 60, 80, 100, 120, 140]);
    const window = halfHourly(145, (index) => (refusals.has(index) ? 403 : 200));
    const first = summarize(window).verdict;
    assert.equal(first.window_served, 137);
    assert.equal(first.outcome, "not served");

    // 48 more good probes would make 185 of 193 overall; the window does not grow.
    const later = summarize([...window, ...halfHourly(48, () => 200, 145)]).verdict;
    assert.deepEqual(later, first);
  });

  it("gives no verdict when the window holds too few scheduled probes", () => {
    // Every fifth half-hour lost (a KV quota, a gap): 116 probes, all served, are too few.
    const sparse = halfHourly(145).filter((_, index) => index % 5 !== 1);
    const verdict = summarize(sparse).verdict;
    assert.ok(verdict.window_probes < VERDICT_MIN_PROBES);
    assert.equal(verdict.outcome, "too few probes");

    // Two probes 72 hours apart are not a verdict either.
    const two = [record(start, 200), record(hoursAfter(start, 72), 200)];
    assert.equal(summarize(two).verdict.outcome, "too few probes");

    // The first probe, the one at the window's end, and enough between: exactly the minimum
    // is a verdict, one fewer is not.
    const closing = halfHourly(1, () => 200, 144);
    const minimum = [...halfHourly(VERDICT_MIN_PROBES - 1), ...closing];
    assert.equal(summarize(minimum).verdict.window_probes, VERDICT_MIN_PROBES);
    assert.equal(summarize(minimum).verdict.outcome, "served");
    const oneShort = [...halfHourly(VERDICT_MIN_PROBES - 2), ...closing];
    assert.equal(summarize(oneShort).verdict.outcome, "too few probes");
  });

  it("counts exactly 95 percent as served and anything less as not", () => {
    // 160 scheduled probes spread over the 72 hours, both ends included.
    const spread = (servedCount) =>
      Array.from({ length: 160 }, (_, index) =>
        record(hoursAfter(start, (72 * index) / 159), index < servedCount ? 200 : 403),
      );
    const exact = summarize(spread(152)).verdict;
    assert.equal(exact.window_probes, 160);
    assert.equal(exact.outcome, "served");
    assert.equal(summarize(spread(151)).verdict.outcome, "not served");
  });

  it("reads only the scheduled probes: live probes cannot move it", () => {
    // 20 refusals among 145 scheduled probes, then 300 served live probes in one stretch.
    const scheduled = halfHourly(145, (index) => (index % 7 === 0 && index < 140 ? 403 : 200));
    const live = Array.from({ length: 300 }, (_, index) =>
      record(new Date(Date.parse(start) + 60_000 * (index + 1)).toISOString(), 200, true, "now"),
    );
    const summary = summarize([...scheduled, ...live]);
    assert.equal(summary.verdict.window_probes, 145);
    assert.equal(summary.verdict.window_served, 125);
    assert.equal(summary.verdict.outcome, "not served");
    assert.deepEqual(summary.by_trigger, { cron: 145, now: 300 });
    const liveStandings = summary.live.find((entry) => entry.target === STANDINGS_URL);
    assert.equal(liveStandings.probes, 300);
    assert.equal(liveStandings.served, 300);
    const scheduledStandings = summary.scheduled.find((entry) => entry.target === STANDINGS_URL);
    assert.equal(scheduledStandings.probes, 145);
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
    const worker = createWorker();
    const env = probeEnv();
    for (const [method, path] of [
      ["POST", RESULTS_PATH],
      ["HEAD", NOW_PATH],
      ["GET", "/api/v1/fpl-probe/now/extra"],
      ["GET", "/api/v1/fpl-probe-other"],
      ["GET", "/api/v1/fpl-probe/.cache/results"],
    ]) {
      const response = await worker.fetch(new Request(`${SITE}${path}`, { method }), env);
      assert.equal(response.status, 404, `${method} ${path}`);
      assert.equal(response.headers.get("cache-control"), "no-store");
      assert.equal(response.headers.get(PROBE_HEADER), MARKER_VALUE);
      if (method !== "HEAD") assert.deepEqual(await response.json(), { error: "not_found" });
    }
    assert.equal(fetch.mock.callCount(), 0);
    assert.equal(env.PROBE.entries.size, 0);
  });

  it("is deployed on one prefix route of the site's host, with no workers.dev address", async () => {
    const config = await readFile(new URL("../wrangler.toml", import.meta.url), "utf8");
    const patterns = [...config.matchAll(/pattern\s*=\s*"([^"]*)"/g)].map((match) => match[1]);
    assert.deepEqual(patterns, ["squadopt.mymandev.com/api/v1/fpl-probe*"]);
    assert.match(config, /zone_name\s*=\s*"mymandev\.com"/);
    assert.match(config, /^workers_dev = false$/m);
    assert.match(config, /^crons = \["\*\/30 \* \* \* \*"\]$/m);
    // The committed file never carries an account's namespace id; the workflow fills it in.
    assert.match(config, /^id = "FILLED_IN_BY_THE_DEPLOY_WORKFLOW"$/m);
    // The end comes from the deploy, never from a committed date.
    assert.doesNotMatch(config, /^PROBE_UNTIL\s*=/m);
    // Workers Logs keep the probe's own lines, not a log of every caller's request.
    assert.match(config, /^\[observability\.logs\]\ninvocation_logs = false$/m);
  });

  it("exports nothing from the entry point but the handlers", async () => {
    const module = await import("../src/index.js");
    assert.deepEqual(Object.keys(module), ["default"]);
    assert.equal(typeof entry.fetch, "function");
    assert.equal(typeof entry.scheduled, "function");
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
    const env = probeEnv();

    await createWorker().scheduled({ cron: "*/30 * * * *", scheduledTime: Date.now() }, env);

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
      const stored = env.PROBE.entries.get(key);
      assert.equal(stored.expirationTtl, RECORD_TTL_SECONDS);
      assert.deepEqual(stored.metadata, JSON.parse(stored.value));
      assert.equal(stored.metadata.target, TARGETS[index]);
      assert.equal(stored.metadata.trigger, "cron");
      assert.equal(stored.metadata.colo, "LHR");
    }
    assert.equal(env.PROBE.entries.get(keys[1]).metadata.status, 403);
    assert.equal(env.PROBE.entries.get(keys[1]).metadata.head, "<html>denied</html>");
  });

  it("asks FPL nothing and writes nothing once PROBE_UNTIL has passed or was never set", async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => {
      throw new Error("no request may leave");
    });
    const worker = createWorker();
    const past = new Date(Date.now() - 1_000).toISOString();
    for (const until of [past, undefined, "", "not a time"]) {
      const env = { PROBE: memoryKv(), PROBE_UNTIL: until };
      await worker.scheduled({ cron: "*/30 * * * *", scheduledTime: Date.now() }, env);
      const response = await worker.fetch(liveRequest(), env);
      assert.equal(response.status, 410, String(until));
      assert.equal((await response.json()).error, "ended");
      assert.equal(env.PROBE.counts.put, 0);
    }
    assert.equal(fetch.mock.callCount(), 0);
  });

  it("returns every stored record in time order with the summary, never cached by the caller", async () => {
    const env = probeEnv(memoryKv({ pageSize: 2 }));
    const stored = [
      ["2026-10-05T11:30:00.000Z", 1, record("2026-10-05T11:30:01.000Z", 200)],
      ["2026-10-05T11:00:00.000Z", 1, record("2026-10-05T11:00:01.000Z", 403)],
      ["2026-10-05T12:00:00.000Z", 1, record("2026-10-05T12:00:01.000Z", 200)],
    ];
    for (const [runAt, index, value] of stored) {
      await env.PROBE.put(recordKey(runAt, index), JSON.stringify(value), { metadata: value });
    }
    // A record whose metadata did not fit is read from its value.
    const late = record("2026-10-05T12:30:01.000Z", 200);
    await env.PROBE.put(recordKey("2026-10-05T12:30:00.000Z", 1), JSON.stringify(late));
    await env.PROBE.put(NOW_GATE_KEY, JSON.stringify({ last: 0, day: "1970-01-01", count: 1 }));

    const response = await createWorker().fetch(new Request(`${SITE}${RESULTS_PATH}`), env);
    assert.equal(response.status, 200);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.get(PROBE_HEADER), MARKER_VALUE);
    assert.match(response.headers.get("content-type"), /^application\/json/);
    const body = await response.json();
    assert.deepEqual(
      body.records.map((value) => value.at),
      [
        "2026-10-05T11:00:01.000Z",
        "2026-10-05T11:30:01.000Z",
        "2026-10-05T12:00:01.000Z",
        "2026-10-05T12:30:01.000Z",
      ],
    );
    assert.equal(body.probe_until, env.PROBE_UNTIL);
    assert.equal(body.summary.probes, 4);
    assert.equal(body.summary.verdict.window_served, 3);
  });

  it("builds the results once per cache period, however many readers ask", async (t) => {
    const cache = memoryCache();
    globalThis.caches = { default: cache };
    t.after(() => {
      delete globalThis.caches;
    });
    const env = probeEnv();
    const value = record("2026-10-05T11:00:01.000Z", 200);
    await env.PROBE.put(recordKey("2026-10-05T11:00:00.000Z", 1), JSON.stringify(value), {
      metadata: value,
    });
    const worker = createWorker();

    const bodies = [];
    for (let read = 0; read < 5; read += 1) {
      const response = await worker.fetch(new Request(`${SITE}${RESULTS_PATH}?n=${read}`), env);
      assert.equal(response.status, 200);
      assert.equal(response.headers.get("cache-control"), "no-store");
      assert.equal(response.headers.get(PROBE_HEADER), MARKER_VALUE);
      bodies.push(await response.text());
    }
    assert.equal(env.PROBE.counts.list, 1, "four of five readers cost no KV list");
    assert.equal(new Set(bodies).size, 1);
    assert.deepEqual([...cache.stored.keys()], [`${SITE}/api/v1/fpl-probe/.cache/results`]);
    const [kept] = cache.stored.values();
    assert.equal(kept.headers["cache-control"], "max-age=300");
  });

  it("runs the live probe only for a caller that sends the probe's header", async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => {
      throw new Error("no request may leave");
    });
    const env = probeEnv();
    const worker = createWorker();
    for (const headers of [{}, { [PROBE_HEADER]: "1" }, { [PROBE_HEADER]: "NOW" }]) {
      const response = await worker.fetch(liveRequest(headers), env);
      assert.equal(response.status, 400);
      assert.equal((await response.json()).error, "missing_header");
    }
    assert.equal(fetch.mock.callCount(), 0);
    assert.equal(env.PROBE.entries.size, 0);
  });

  it("runs the live probe at most once a minute for everyone, and keeps no data centre", async (t) => {
    const standings = () => Response.json({ standings: { results: ["PRIVATE-MARKER"] } });
    const fetch = t.mock.method(globalThis, "fetch", fplAnswers({ standings }));
    const env = probeEnv();
    const worker = createWorker();

    const first = await worker.fetch(liveRequest(), env);
    assert.equal(first.status, 200);
    assert.equal(first.headers.get("cache-control"), "no-store");
    const text = await first.text();
    assert.ok(!text.includes("PRIVATE-MARKER"), "a caller never receives FPL's body");
    const body = JSON.parse(text);
    assert.equal(body.stored, true);
    assert.deepEqual(
      body.records.map((value) => [value.target, value.status, value.json, value.trigger]),
      [
        [EVENT_STATUS_URL, 200, true, "now"],
        [STANDINGS_URL, 200, true, "now"],
      ],
    );
    assert.equal(fetch.mock.callCount(), 2, "a live probe needs no trace");
    const records = [...env.PROBE.entries].filter(([key]) => key.startsWith("r:"));
    assert.equal(records.length, 2);
    for (const [, stored] of records) assert.equal(stored.metadata.colo, null);
    assert.equal(env.PROBE.counts.put, 3, "one gate write and two records");
    const gate = env.PROBE.entries.get(NOW_GATE_KEY);
    assert.equal(gate.expirationTtl, NOW_GATE_TTL_SECONDS);
    assert.equal(JSON.parse(gate.value).count, 1);

    const second = await worker.fetch(liveRequest(), env);
    assert.equal(second.status, 429);
    assert.equal(second.headers.get("cache-control"), "no-store");
    const refusal = await second.json();
    assert.equal(refusal.error, "too_many_requests");
    assert.equal(second.headers.get("retry-after"), String(refusal.retry_after_seconds));
    assert.equal(fetch.mock.callCount(), 2, "a refused caller sends nothing to FPL");

    // Another isolate, which has not run it, still reads the KV gate.
    const elsewhere = await createWorker().fetch(liveRequest(), env);
    assert.equal(elsewhere.status, 429);
    assert.equal(fetch.mock.callCount(), 2);
  });

  it("lets one of many concurrent callers in one isolate through", async (t) => {
    const fetch = t.mock.method(
      globalThis,
      "fetch",
      fplAnswers({ standings: () => Response.json({}) }),
    );
    const env = probeEnv();
    const worker = createWorker();

    const answers = await Promise.all(
      Array.from({ length: 20 }, () => worker.fetch(liveRequest(), env)),
    );
    const statuses = answers.map((response) => response.status);
    assert.equal(statuses.filter((status) => status === 200).length, 1);
    assert.equal(statuses.filter((status) => status === 429).length, 19);
    assert.equal(fetch.mock.callCount(), 2);
    assert.equal(env.PROBE.counts.put, 3);
  });

  it("refuses the live probe once it has run its daily number of times", async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => {
      throw new Error("no request may leave");
    });
    const env = probeEnv();
    const nowMs = Date.now();
    const today = new Date(nowMs).toISOString().slice(0, 10);
    await env.PROBE.put(
      NOW_GATE_KEY,
      JSON.stringify({ last: nowMs - 3_600_000, day: today, count: NOW_DAILY_CAP }),
    );
    const writes = env.PROBE.counts.put;

    const response = await createWorker().fetch(liveRequest(), env);
    assert.equal(response.status, 429);
    const refusal = await response.json();
    assert.match(refusal.detail, /this UTC day/);
    assert.ok(refusal.retry_after_seconds >= 1 && refusal.retry_after_seconds <= 86_400);
    assert.equal(fetch.mock.callCount(), 0);
    assert.equal(env.PROBE.counts.put, writes);
  });

  it("refuses the live probe when it cannot record that it ran", async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => {
      throw new Error("no request may leave");
    });
    const kv = memoryKv();
    kv.put = async () => {
      throw new Error("KV put() limit exceeded for the day.");
    };

    const response = await createWorker().fetch(liveRequest(), probeEnv(kv));
    assert.equal(response.status, 503);
    assert.equal(response.headers.get(PROBE_HEADER), MARKER_VALUE);
    assert.equal((await response.json()).error, "unavailable");
    assert.equal(fetch.mock.callCount(), 0);
  });
});

describe("the live probe gate", () => {
  const now = Date.parse("2026-10-05T12:00:00.000Z");
  const gate = (last, count = 1, day = "2026-10-05") => JSON.stringify({ last, day, count });

  it("opens with no stored gate, after a minute, and not before", () => {
    for (const text of [null, undefined, "not json", "1759665600000", "{}"]) {
      const opened = nowGate(text, now);
      assert.equal(opened.allowed, true, String(text));
      assert.deepEqual(JSON.parse(opened.next), { last: now, day: "2026-10-05", count: 1 });
    }
    assert.equal(nowGate(gate(now - 60_000), now).allowed, true);
    assert.deepEqual(nowGate(gate(now - 59_001), now), {
      allowed: false,
      reason: "interval",
      retryAfterSeconds: 1,
    });
    assert.equal(nowGate(gate(now - 1_000), now).retryAfterSeconds, 59);
    assert.equal(nowGate(gate(now + 5_000), now).retryAfterSeconds, 60);
  });

  it("counts the runs of one UTC day and starts again on the next", () => {
    const opened = nowGate(gate(now - 120_000, 5), now);
    assert.equal(JSON.parse(opened.next).count, 6);

    const capped = nowGate(gate(now - 120_000, NOW_DAILY_CAP), now);
    assert.equal(capped.allowed, false);
    assert.equal(capped.reason, "daily_cap");
    assert.equal(capped.retryAfterSeconds, 12 * 3600, "until 00:00 UTC");

    const yesterday = nowGate(gate(now - 13 * 3_600_000, NOW_DAILY_CAP, "2026-10-04"), now);
    assert.equal(yesterday.allowed, true);
    assert.equal(JSON.parse(yesterday.next).count, 1);
  });

  it("allows at most the daily number of runs a day, three KV writes each", () => {
    let stored = null;
    let allowed = 0;
    for (let minute = 0; minute < 24 * 60; minute += 1) {
      const result = nowGate(stored, Date.parse("2026-10-05T00:00:00.000Z") + minute * 60_000);
      if (result.allowed) {
        allowed += 1;
        stored = result.next;
      }
    }
    assert.equal(allowed, NOW_DAILY_CAP);
    assert.ok(allowed * 3 + 96 < 1_000, "the schedule keeps its writes inside the Free plan");
  });
});

describe("the probe's end", () => {
  it("runs only before a readable PROBE_UNTIL", () => {
    const now = Date.parse("2026-10-05T12:00:00.000Z");
    assert.equal(probeActive("2026-10-12T12:00:00.000Z", now), true);
    assert.equal(probeActive("2026-10-05T12:00:00.000Z", now), false);
    assert.equal(probeActive("2026-10-01T00:00:00.000Z", now), false);
    for (const missing of [undefined, null, "", "  ", "soon"]) {
      assert.equal(probeActive(missing, now), false, String(missing));
    }
  });
});
