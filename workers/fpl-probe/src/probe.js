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

/**
 * The deploy workflow passes PROBE_UNTIL, this many days after the deploy. From then on the
 * schedule and the live probe ask FPL nothing, so a probe nobody deletes stops by itself.
 */
export const PROBE_DAYS = 7;

/** The live probe runs at most once in this window, whoever asks. */
export const NOW_INTERVAL_MS = 60_000;

/** And at most this many times a UTC day, whoever asks: 3 KV writes each, 144 a day at most. */
export const NOW_DAILY_CAP = 48;

/** The KV key holding the live probe's gate: when it last ran, on which UTC day, how often. */
export const NOW_GATE_KEY = "now:gate";

/** The gate outlives the UTC day it counts, then expires by itself. */
export const NOW_GATE_TTL_SECONDS = 2 * 24 * 60 * 60;

/**
 * A live probe must carry this request header with the value "now". A page on another site
 * cannot add it without a CORS preflight, which the Worker never grants, so a browser cannot be
 * made to run the probe from someone else's page. Every answer of the Worker carries the same
 * header with the value "1", so the deploy workflow can tell the Worker from anything else.
 */
export const PROBE_HEADER = "x-squadopt-probe";
export const NOW_HEADER_VALUE = "now";
export const MARKER_VALUE = "1";

/** Every record key starts with this, so one prefix lists them all in time order. */
export const RECORD_PREFIX = "r:";

export const RESULTS_PATH = "/api/v1/fpl-probe";
export const NOW_PATH = "/api/v1/fpl-probe/now";

/** The results answer is built at most once per data centre in this many seconds. */
export const RESULTS_CACHE_SECONDS = 300;

/** The most of a non-JSON answer a record keeps: enough to tell a block page from an outage. */
export const HEAD_CHARACTERS = 120;

/** KV refuses metadata larger than this, serialized. */
export const METADATA_LIMIT_BYTES = 1024;

/**
 * The verdict rule, fixed before any data (docs/fpl_forwarder_probe.md): the scheduled standings
 * probes in the first 72 hours from the first of them, both ends included, which is 145 probes at
 * one every 30 minutes. Fewer than VERDICT_MIN_PROBES of them is no verdict.
 */
export const VERDICT_PERCENT = 95;
export const VERDICT_HOURS = 72;
export const VERDICT_WINDOW_MS = VERDICT_HOURS * 3_600_000;
export const VERDICT_EXPECTED_PROBES = 145;
export const VERDICT_MIN_PROBES = 130;

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
 * Whether the probe is still meant to run: PROBE_UNTIL must be a time, and it must lie ahead.
 * A missing or unreadable end refuses, so a deploy without one probes nothing.
 */
export function probeActive(untilText, nowMs) {
  if (typeof untilText !== "string" || untilText.trim() === "") return false;
  const until = Date.parse(untilText);
  return Number.isFinite(until) && nowMs < until;
}

function utcDay(ms) {
  return new Date(ms).toISOString().slice(0, 10);
}

function readGate(text) {
  if (typeof text !== "string") return null;
  try {
    const value = JSON.parse(text);
    if (
      value !== null &&
      typeof value === "object" &&
      Number.isFinite(value.last) &&
      typeof value.day === "string" &&
      Number.isInteger(value.count) &&
      value.count >= 0
    ) {
      return value;
    }
  } catch {
    // An unreadable gate is treated as no gate; only the Worker writes it.
  }
  return null;
}

/**
 * Whether the live probe may run now, given the stored gate (JSON text from KV, or null when
 * there is none). The gate holds { last, day, count }: the time of the last live probe, its UTC
 * day, and how many ran on that day. A run is refused within NOW_INTERVAL_MS of the last one,
 * and once NOW_DAILY_CAP have run on this UTC day. A refusal says how many whole seconds remain;
 * an allowed run carries the gate to write, so each allowed run costs one write. A stored time
 * ahead of this clock refuses too: another data centre has just run it.
 */
export function nowGate(
  gateText,
  nowMs,
  { intervalMs = NOW_INTERVAL_MS, dailyCap = NOW_DAILY_CAP } = {},
) {
  const gate = readGate(gateText);
  const today = utcDay(nowMs);
  const countToday = gate !== null && gate.day === today ? gate.count : 0;
  if (gate !== null) {
    const elapsed = nowMs - gate.last;
    if (elapsed < intervalMs) {
      const windowSeconds = Math.ceil(intervalMs / 1000);
      const remaining = Math.ceil((intervalMs - elapsed) / 1000);
      return {
        allowed: false,
        reason: "interval",
        retryAfterSeconds: Math.min(windowSeconds, Math.max(1, remaining)),
      };
    }
  }
  if (countToday >= dailyCap) {
    const nextDay = Date.parse(`${today}T00:00:00.000Z`) + 86_400_000;
    return {
      allowed: false,
      reason: "daily_cap",
      retryAfterSeconds: Math.max(1, Math.ceil((nextDay - nowMs) / 1000)),
    };
  }
  return {
    allowed: true,
    retryAfterSeconds: 0,
    next: JSON.stringify({ last: nowMs, day: today, count: countToday + 1 }),
  };
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

/** Hours between two ISO times, rounded for reading only; no rule compares this number. */
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

function byTarget(records) {
  const groups = new Map(TARGETS.map((target) => [target, []]));
  for (const record of records) {
    if (!groups.has(record.target)) groups.set(record.target, []);
    groups.get(record.target).push(record);
  }
  return [...groups].map(([target, group]) => summarizeTarget(target, group));
}

/**
 * The rule fixed in docs/fpl_forwarder_probe.md, applied to the scheduled standings probes in
 * time order. The window is the first VERDICT_HOURS from the first of them, both ends included,
 * so reading later never moves it. Until a scheduled standings probe exists at or after the
 * window's end the outcome is "pending"; then it is "too few probes" when the window holds
 * fewer than VERDICT_MIN_PROBES, and otherwise "served" or "not served", and it stays so.
 * Times are compared in whole milliseconds and the share in integers, so nothing rounds.
 */
export function verdictFor(scheduledStandings) {
  const rule =
    `served when at least ${VERDICT_PERCENT} percent of the scheduled standings probes in the ` +
    `first ${VERDICT_HOURS} hours from the first of them answer 200 JSON, with at least ` +
    `${VERDICT_MIN_PROBES} of the ${VERDICT_EXPECTED_PROBES} expected probes in that window`;
  if (scheduledStandings.length === 0) {
    return {
      rule,
      window_from: null,
      window_to: null,
      window_probes: 0,
      window_served: 0,
      share: null,
      min_probes: VERDICT_MIN_PROBES,
      outcome: "pending",
    };
  }
  const fromMs = Date.parse(scheduledStandings[0].at);
  const toMs = fromMs + VERDICT_WINDOW_MS;
  const inWindow = scheduledStandings.filter((record) => Date.parse(record.at) <= toMs);
  const served = inWindow.filter(isServed).length;
  const closed = scheduledStandings.some((record) => Date.parse(record.at) >= toMs);

  let outcome = "pending";
  if (closed && inWindow.length < VERDICT_MIN_PROBES) outcome = "too few probes";
  else if (closed) {
    outcome = served * 100 >= VERDICT_PERCENT * inWindow.length ? "served" : "not served";
  }
  return {
    rule,
    window_from: new Date(fromMs).toISOString(),
    window_to: new Date(toMs).toISOString(),
    window_probes: inWindow.length,
    window_served: served,
    share: Math.round((served / inWindow.length) * 10_000) / 10_000,
    min_probes: VERDICT_MIN_PROBES,
    outcome,
  };
}

/**
 * The record read as a whole. `scheduled` and `live` hold, per target, the probes of the cron
 * and of /now apart: how many probes, how many were served, the count of each status (or
 * "timeout" and "error" for a probe that got no answer), the first and last time, the longest
 * run of consecutive failures with when it began and ended, and the longest gap between two
 * probes. The verdict reads only the scheduled standings probes: a caller of /now chooses when
 * and from which data centre a live probe runs, so live probes are context, never evidence.
 */
export function summarize(records) {
  const ordered = [...records].sort(byTime);
  const scheduled = ordered.filter((record) => record.trigger === "cron");
  const live = ordered.filter((record) => record.trigger === "now");
  const byTrigger = {};
  for (const record of ordered) {
    const key = String(record.trigger);
    byTrigger[key] = (byTrigger[key] ?? 0) + 1;
  }

  return {
    probes: ordered.length,
    first_at: ordered.length > 0 ? ordered[0].at : null,
    last_at: ordered.length > 0 ? ordered[ordered.length - 1].at : null,
    by_trigger: byTrigger,
    scheduled: byTarget(scheduled),
    live: byTarget(live),
    verdict: verdictFor(scheduled.filter((record) => record.target === STANDINGS_URL)),
  };
}
