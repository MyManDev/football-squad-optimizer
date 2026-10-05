// What the FPL probe asks, what it keeps of each answer, and how it reads its own record.
//
// Nothing here touches the network, the clock or storage: index.js does the fetching and the
// writing and hands each outcome to this module as plain data, so every rule about what a
// record holds can be tested under node --test. See docs/fpl_forwarder_probe.md.

/** The user agent the capture sends (USER_AGENT in src/squadopt/platform/fpl_capture.py). */
export const USER_AGENT = "squadopt/1.0 (private research; contact via repository owner)";

/** The cheapest FPL answer: a few hundred bytes saying whether the week's points are final. */
export const EVENT_STATUS_URL = "https://fantasy.premierleague.com/api/event-status/";

/** The answer a forwarder would exist to serve: the league table members open. */
export const STANDINGS_URL =
  "https://fantasy.premierleague.com/api/leagues-classic/352490/standings/";

/** Probed in this order, once each per run. A record's key carries the index. */
export const TARGETS = Object.freeze([EVENT_STATUS_URL, STANDINGS_URL]);

/** One probe gives up after this long, so a run waits on FPL for at most two of these. */
export const PROBE_TIMEOUT_MS = 10_000;

/** A record outlives the 3 to 5 day probe with room to read it afterwards. */
export const RECORD_TTL_SECONDS = 14 * 24 * 60 * 60;

/** The live probe runs at most once in this window, whoever asks. */
export const NOW_INTERVAL_MS = 60_000;

/** The KV key holding the time the live probe last ran. */
export const LAST_NOW_KEY = "now:last";

/** Every record key starts with this, so one prefix lists them all in time order. */
export const RECORD_PREFIX = "r:";

export const RESULTS_PATH = "/api/v1/fpl-probe";
export const NOW_PATH = "/api/v1/fpl-probe/now";

/** The most of a non-JSON answer a record keeps: enough to tell a block page from an outage. */
export const HEAD_CHARACTERS = 120;

/** KV refuses metadata larger than this, serialized. */
export const METADATA_LIMIT_BYTES = 1024;

/** The verdict rule, fixed before any data (docs/fpl_forwarder_probe.md). */
export const VERDICT_SHARE = 0.95;
export const VERDICT_HOURS = 72;

const ERROR_CHARACTERS = 160;
const CONTENT_TYPE_CHARACTERS = 100;
const COLO_CHARACTERS = 8;

/** The KV key of one record: the run's start time, then the target's index. */
export function recordKey(runAt, index) {
  return `${RECORD_PREFIX}${runAt}:${index}`;
}

/**
 * Which answer a request gets: "results", "now", or null for the 404 every other path and
 * every other method receives. Only the path is read; a query string changes nothing.
 */
export function routeFor(method, pathname) {
  if (method !== "GET") return null;
  if (pathname === RESULTS_PATH) return "results";
  if (pathname === NOW_PATH) return "now";
  return null;
}

/**
 * Whether the live probe may run now, given the stored time of its last run (text from KV, or
 * null when there is none). A refusal says how many whole seconds remain. A stored time ahead
 * of this clock refuses too: another data centre has just run it, and the key expires anyway.
 */
export function nowGate(lastText, nowMs, intervalMs = NOW_INTERVAL_MS) {
  const last = lastText === null || lastText === undefined ? NaN : Number(lastText);
  if (!Number.isFinite(last)) return { allowed: true, retryAfterSeconds: 0 };
  const elapsed = nowMs - last;
  if (elapsed >= intervalMs) return { allowed: true, retryAfterSeconds: 0 };
  const windowSeconds = Math.ceil(intervalMs / 1000);
  const remaining = Math.ceil((intervalMs - elapsed) / 1000);
  return { allowed: false, retryAfterSeconds: Math.min(windowSeconds, Math.max(1, remaining)) };
}

function clip(value, characters) {
  if (value === null || value === undefined) return null;
  const points = Array.from(String(value));
  return points.slice(0, characters).join("");
}

function headOf(text) {
  // Control characters and runs of whitespace become one space, so the head reads as a line.
  const flat = text
    .replace(/[\u0000-\u001f\u007f]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return clip(flat, HEAD_CHARACTERS);
}

function parsesAsJson(text) {
  try {
    const value = JSON.parse(text);
    return value !== null && typeof value === "object";
  } catch {
    return false;
  }
}

function describeError(error) {
  if (error && (error.name === "TimeoutError" || error.name === "AbortError")) {
    return `timeout after ${PROBE_TIMEOUT_MS} ms`;
  }
  if (error instanceof Error) return clip(`${error.name}: ${error.message}`, ERROR_CHARACTERS);
  return clip(String(error), ERROR_CHARACTERS);
}

function bodyBytes(body) {
  if (body === null || body === undefined) return new Uint8Array(0);
  if (typeof body === "string") return new TextEncoder().encode(body);
  if (body instanceof ArrayBuffer) return new Uint8Array(body);
  if (ArrayBuffer.isView(body)) {
    return new Uint8Array(body.buffer, body.byteOffset, body.byteLength);
  }
  throw new TypeError("a probe body must be text, an ArrayBuffer or a typed array");
}

/**
 * One fetch outcome as the small record the probe stores.
 *
 * The outcome is { at, target, trigger, colo, ms } plus either `error` (the thrown value) or
 * `status`, `contentType` and `body`. The body is read here and dropped: a record keeps its
 * size, whether it parsed as JSON, and, for an answer that is not JSON, the first
 * HEAD_CHARACTERS characters of its text. A JSON answer keeps nothing of its body.
 */
export function recordFrom(outcome) {
  const base = {
    at: outcome.at,
    trigger: outcome.trigger ?? null,
    target: outcome.target,
  };
  const ms = Number.isFinite(outcome.ms) ? Math.max(0, Math.round(outcome.ms)) : null;
  const colo = clip(outcome.colo ?? null, COLO_CHARACTERS);

  if (outcome.error !== undefined && outcome.error !== null) {
    return {
      ...base,
      status: null,
      ms,
      bytes: null,
      content_type: null,
      json: false,
      head: null,
      colo,
      error: describeError(outcome.error),
    };
  }

  const bytes = bodyBytes(outcome.body);
  const text = new TextDecoder().decode(bytes);
  const json = parsesAsJson(text);
  return {
    ...base,
    status: Number.isInteger(outcome.status) ? outcome.status : null,
    ms,
    bytes: bytes.byteLength,
    content_type: clip(outcome.contentType ?? null, CONTENT_TYPE_CHARACTERS),
    json,
    head: json ? null : headOf(text),
    colo,
    error: null,
  };
}

/** The record as KV metadata, or null when it would not fit (the value still holds it). */
export function metadataFor(record) {
  const size = new TextEncoder().encode(JSON.stringify(record)).byteLength;
  return size <= METADATA_LIMIT_BYTES ? record : null;
}

/** Served means what a forwarder needs: HTTP 200 carrying JSON. */
export function isServed(record) {
  return record.status === 200 && record.json === true;
}

function statusKey(record) {
  if (Number.isInteger(record.status)) return String(record.status);
  const timedOut = typeof record.error === "string" && record.error.startsWith("timeout");
  return timedOut ? "timeout" : "error";
}

function hoursBetween(from, to) {
  if (from === null || to === null) return 0;
  return Math.round(((Date.parse(to) - Date.parse(from)) / 3_600_000) * 100) / 100;
}

function byTime(left, right) {
  if (left.at < right.at) return -1;
  if (left.at > right.at) return 1;
  return TARGETS.indexOf(left.target) - TARGETS.indexOf(right.target);
}

function summarizeTarget(target, records) {
  const byStatus = {};
  let served = 0;
  let run = null;
  let longest = { length: 0, from: null, to: null };
  let longestGapMs = 0;

  records.forEach((record, index) => {
    const key = statusKey(record);
    byStatus[key] = (byStatus[key] ?? 0) + 1;
    if (isServed(record)) {
      served += 1;
      run = null;
    } else {
      run =
        run === null
          ? { length: 1, from: record.at, to: record.at }
          : { length: run.length + 1, from: run.from, to: record.at };
      if (run.length > longest.length) longest = run;
    }
    if (index > 0) {
      const gap = Date.parse(record.at) - Date.parse(records[index - 1].at);
      longestGapMs = Math.max(longestGapMs, gap);
    }
  });

  const firstAt = records.length > 0 ? records[0].at : null;
  const lastAt = records.length > 0 ? records[records.length - 1].at : null;
  const share = records.length > 0 ? Math.round((served / records.length) * 10_000) / 10_000 : null;
  return {
    target,
    probes: records.length,
    served,
    served_share: share,
    by_status: byStatus,
    first_at: firstAt,
    last_at: lastAt,
    span_hours: hoursBetween(firstAt, lastAt),
    longest_failure_run: longest,
    longest_gap_minutes: Math.round(longestGapMs / 6_000) / 10,
  };
}

/**
 * The record read as a whole: per target, how many probes, how many were served, the count of
 * each status (or "timeout" and "error" for a probe that got no answer), the first and last
 * time, the longest run of consecutive failures with when it began and ended, and the longest
 * gap between two probes. The verdict applies the rule fixed in docs/fpl_forwarder_probe.md to
 * the standings probes; until they span 72 hours it says "pending".
 */
export function summarize(records) {
  const ordered = [...records].sort(byTime);
  const groups = new Map(TARGETS.map((target) => [target, []]));
  for (const record of ordered) {
    if (!groups.has(record.target)) groups.set(record.target, []);
    groups.get(record.target).push(record);
  }
  const targets = [...groups].map(([target, group]) => summarizeTarget(target, group));
  const standings = targets.find((entry) => entry.target === STANDINGS_URL);

  let outcome = "pending";
  if (standings.probes > 0 && standings.span_hours >= VERDICT_HOURS) {
    outcome = standings.served / standings.probes >= VERDICT_SHARE ? "served" : "not served";
  }

  return {
    probes: ordered.length,
    first_at: ordered.length > 0 ? ordered[0].at : null,
    last_at: ordered.length > 0 ? ordered[ordered.length - 1].at : null,
    targets,
    verdict: {
      rule:
        "served when at least 95 percent of the standings probes over at least 72 hours " +
        "answer 200 JSON",
      standings_probes: standings.probes,
      standings_served: standings.served,
      share: standings.served_share,
      span_hours: standings.span_hours,
      outcome,
    },
  };
}
