// The FPL probe Worker: does FPL answer requests that leave from Cloudflare's network?
//
// Every 30 minutes the cron asks each target once and stores what came back as a small record
// (probe.js says what a record keeps). Two GET paths read it: /api/v1/fpl-probe returns every
// stored record and their summary, and /api/v1/fpl-probe/now runs one live probe, at most once
// a minute for everyone. Nothing else answers, and nothing of FPL's answers reaches a caller
// beyond those records. See docs/fpl_forwarder_probe.md.

import {
  LAST_NOW_KEY,
  NOW_INTERVAL_MS,
  PROBE_TIMEOUT_MS,
  RECORD_PREFIX,
  RECORD_TTL_SECONDS,
  TARGETS,
  USER_AGENT,
  metadataFor,
  nowGate,
  recordFrom,
  recordKey,
  routeFor,
  summarize,
} from "./probe.js";

/** Cloudflare's own trace names the data centre a scheduled run is in; a cron has no request. */
const TRACE_URL = "https://www.cloudflare.com/cdn-cgi/trace";
const TRACE_TIMEOUT_MS = 5_000;

/** The gate key outlives its window, then expires by itself. KV's shortest TTL is 60 s. */
const LAST_NOW_TTL_SECONDS = 120;

function answer(status, body, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      ...headers,
    },
  });
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

async function results(env) {
  const records = await readRecords(env);
  return answer(200, {
    generated_at: new Date().toISOString(),
    records,
    summary: summarize(records),
  });
}

async function now(request, env) {
  const gate = nowGate(await env.PROBE.get(LAST_NOW_KEY), Date.now());
  if (!gate.allowed) {
    return answer(
      429,
      {
        error: "too_many_requests",
        detail: "the live probe runs at most once a minute",
        retry_after_seconds: gate.retryAfterSeconds,
      },
      { "retry-after": String(gate.retryAfterSeconds) },
    );
  }
  try {
    await env.PROBE.put(LAST_NOW_KEY, String(Date.now()), {
      expirationTtl: LAST_NOW_TTL_SECONDS,
    });
  } catch (error) {
    // Without the gate written, nothing would stop the next caller; refuse rather than probe.
    log("gate_failed", { error: String(error) });
    return answer(503, { error: "unavailable", detail: "the live probe gate could not be set" });
  }
  const colo = typeof request.cf?.colo === "string" ? request.cf.colo : null;
  const { records, stored } = await probeAll(env, "now", colo);
  return answer(200, { records, stored });
}

export default {
  async scheduled(controller, env) {
    const colo = await traceColo();
    await probeAll(env, "cron", colo);
  },

  async fetch(request, env) {
    try {
      const route = routeFor(request.method, new URL(request.url).pathname);
      if (route === "results") return await results(env);
      if (route === "now") return await now(request, env);
      return answer(404, { error: "not_found" });
    } catch (error) {
      log("request_failed", { error: String(error) });
      return answer(500, { error: "internal" });
    }
  },
};
