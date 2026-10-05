// The FPL probe Worker's handlers: does FPL answer requests that leave from Cloudflare's network?
//
// Every 30 minutes the cron asks each target once and stores what came back as a small record
// (probe.js says what a record keeps). Two GET paths read it: /api/v1/fpl-probe returns every
// stored record and their summary, and /api/v1/fpl-probe/now runs one live probe for a caller
// that sends the x-squadopt-probe: now header, at most once a minute and 48 times a UTC day for
// everyone. Nothing else answers, and nothing of FPL's answers reaches a caller beyond those
// records. After PROBE_UNTIL the Worker asks FPL nothing. See docs/fpl_forwarder_probe.md.
//
// index.js is the entry point and exports one set of these handlers; tests build their own.

import {
  MARKER_VALUE,
  NOW_GATE_KEY,
  NOW_GATE_TTL_SECONDS,
  NOW_HEADER_VALUE,
  NOW_INTERVAL_MS,
  PROBE_HEADER,
  PROBE_TIMEOUT_MS,
  RECORD_PREFIX,
  RECORD_TTL_SECONDS,
  RESULTS_CACHE_SECONDS,
  TARGETS,
  USER_AGENT,
  metadataFor,
  nowGate,
  probeActive,
  recordFrom,
  recordKey,
  routeFor,
  summarize,
} from "./probe.js";

/** Cloudflare's own trace names the data centre a scheduled run is in; a cron has no request. */
const TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace";
const TRACE_TIMEOUT_MS = 5_000;

/**
 * The results answer is cached under this path of the Worker's own host. The route sends the
 * path to the Worker, which answers it with 404, so the cached copy is only ever read here.
 */
const RESULTS_CACHE_PATH = "/api/v1/fpl-probe/.cache/results";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  [PROBE_HEADER]: MARKER_VALUE,
};

function answerText(status, text, headers = {}) {
  return new Response(text, { status, headers: { ...JSON_HEADERS, ...headers } });
}

function answer(status, body, headers = {}) {
  return answerText(status, JSON.stringify(body), headers);
}

function log(event, fields) {
  console.log(JSON.stringify({ event, ...fields }));
}

async function traceColo() {
  try {
    const response = await fetch(TRACE_URL, {
      headers: { "user-agent": USER_AGENT },
      signal: AbortSignal.timeout(TRACE_TIMEOUT_MS),
      cf: { cacheTtl: 0 },
    });
    if (!response.ok) return null;
    const match = /^colo=([A-Za-z0-9]+)$/m.exec(await response.text());
    return match ? match[1] : null;
  } catch {
    return null;
  }
}

/** One request to one target. `cacheTtl: 0` keeps Cloudflare's cache from hiding a refusal. */
async function probeOne(target, trigger, colo) {
  const at = new Date().toISOString();
  const started = Date.now();
  try {
    const response = await fetch(target, {
      method: "GET",
      headers: { "user-agent": USER_AGENT, accept: "application/json" },
      signal: AbortSignal.timeout(PROBE_TIMEOUT_MS),
      cf: { cacheTtl: 0 },
    });
    const body = await response.arrayBuffer();
    return recordFrom({
      at,
      trigger,
      target,
      colo,
      ms: Date.now() - started,
      status: response.status,
      contentType: response.headers.get("content-type"),
      body,
    });
  } catch (error) {
    return recordFrom({ at, trigger, target, colo, ms: Date.now() - started, error });
  }
}

async function store(env, key, record) {
  const metadata = metadataFor(record);
  try {
    await env.PROBE.put(key, JSON.stringify(record), {
      expirationTtl: RECORD_TTL_SECONDS,
      ...(metadata === null ? {} : { metadata }),
    });
    return true;
  } catch (error) {
    log("store_failed", { key, error: String(error) });
    return false;
  }
}

/** Every target once, in order, one after another; each record is stored as it arrives. */
async function probeAll(env, trigger, colo) {
  const runAt = new Date().toISOString();
  const records = [];
  let stored = true;
  for (const [index, target] of TARGETS.entries()) {
    const record = await probeOne(target, trigger, colo);
    log("probe", record);
    records.push(record);
    stored = (await store(env, recordKey(runAt, index), record)) && stored;
  }
  return { records, stored };
}

/** Every stored record in key order, which is time order. Metadata carries each one. */
async function readRecords(env) {
  const records = [];
  let cursor;
  do {
    const page = await env.PROBE.list({ prefix: RECORD_PREFIX, cursor });
    for (const key of page.keys) {
      const record = key.metadata ?? (await env.PROBE.get(key.name, "json"));
      if (record !== null && record !== undefined) records.push(record);
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
  return records;
}

/**
 * Every stored record with its summary. Building it lists KV (one or two list operations, of
 * 1,000 a day on the Free plan) and costs a few milliseconds of CPU, so the built text is kept
 * in this data centre's cache for RESULTS_CACHE_SECONDS and a burst of readers costs one build.
 * The caller still gets `no-store`; `generated_at` says when the answer was built.
 */
async function results(request, env) {
  const cache = globalThis.caches?.default ?? null;
  const key = new Request(new URL(RESULTS_CACHE_PATH, request.url).href);
  if (cache !== null) {
    try {
      const hit = await cache.match(key);
      if (hit) return answerText(200, await hit.text());
    } catch (error) {
      log("cache_read_failed", { error: String(error) });
    }
  }

  const records = await readRecords(env);
  const text = JSON.stringify({
    generated_at: new Date().toISOString(),
    probe_until: typeof env.PROBE_UNTIL === "string" ? env.PROBE_UNTIL : null,
    records,
    summary: summarize(records),
  });
  if (cache !== null) {
    try {
      await cache.put(
        key,
        new Response(text, {
          headers: {
            "content-type": "application/json; charset=utf-8",
            "cache-control": `max-age=${RESULTS_CACHE_SECONDS}`,
          },
        }),
      );
    } catch (error) {
      log("cache_write_failed", { error: String(error) });
    }
  }
  return answerText(200, text);
}

function tooManyRequests(detail, retryAfterSeconds) {
  return answer(
    429,
    { error: "too_many_requests", detail, retry_after_seconds: retryAfterSeconds },
    { "retry-after": String(retryAfterSeconds) },
  );
}

/**
 * The handlers, with the one piece of state an isolate keeps: when it last let a live probe
 * through. That check is made and set before the first await, so concurrent requests in one
 * isolate cannot all read the KV gate before any of them writes it. The KV gate then covers
 * the other isolates and data centres, within the minute KV takes to reach them.
 */
export function createWorker() {
  let isolateLastNowMs = -Infinity;

  async function now(request, env) {
    if (request.headers.get(PROBE_HEADER) !== NOW_HEADER_VALUE) {
      return answer(400, {
        error: "missing_header",
        detail: `the live probe needs the request header ${PROBE_HEADER}: ${NOW_HEADER_VALUE}`,
      });
    }
    if (!probeActive(env.PROBE_UNTIL, Date.now())) {
      return answer(410, { error: "ended", detail: "the probe has ended and asks FPL nothing" });
    }

    const startedMs = Date.now();
    const sinceIsolate = startedMs - isolateLastNowMs;
    if (sinceIsolate < NOW_INTERVAL_MS) {
      const retry = Math.max(1, Math.ceil((NOW_INTERVAL_MS - sinceIsolate) / 1000));
      return tooManyRequests("the live probe runs at most once a minute", retry);
    }
    isolateLastNowMs = startedMs;

    const gate = nowGate(await env.PROBE.get(NOW_GATE_KEY), Date.now());
    if (!gate.allowed) {
      const detail =
        gate.reason === "daily_cap"
          ? "the live probe has run as often as it may this UTC day"
          : "the live probe runs at most once a minute";
      return tooManyRequests(detail, gate.retryAfterSeconds);
    }
    try {
      await env.PROBE.put(NOW_GATE_KEY, gate.next, { expirationTtl: NOW_GATE_TTL_SECONDS });
    } catch (error) {
      // Without the gate written, nothing would stop the next caller; refuse rather than probe.
      log("gate_failed", { error: String(error) });
      return answer(503, { error: "unavailable", detail: "the live probe gate could not be set" });
    }
    // A live record keeps no data centre: it would say where the caller is, not where the
    // schedule runs, and the verdict reads only scheduled records anyway.
    const { records, stored } = await probeAll(env, "now", null);
    return answer(200, { records, stored });
  }

  return {
    async scheduled(controller, env) {
      if (!probeActive(env.PROBE_UNTIL, Date.now())) {
        log("ended", { probe_until: env.PROBE_UNTIL ?? null });
        return;
      }
      const colo = await traceColo();
      await probeAll(env, "cron", colo);
    },

    async fetch(request, env) {
      try {
        const route = routeFor(request.method, new URL(request.url).pathname);
        if (route === "results") return await results(request, env);
        if (route === "now") return await now(request, env);
        return answer(404, { error: "not_found" });
      } catch (error) {
        log("request_failed", { error: String(error) });
        return answer(500, { error: "internal" });
      }
    },
  };
}
