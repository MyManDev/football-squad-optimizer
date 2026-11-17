// The usage Worker: one route takes an event from the site's pages and writes it to Analytics
// Engine, one says whether the Worker is bound to its dataset. It reads no address and no
// cookie, keeps nothing of its own, and logs nothing of what a page sent.
//
// Two more routes serve the record to the people the Cloudflare Access policy names (ADR 0016):
// the report for a range, and a bare "you are an admin" answer the site's heatmap button asks
// first. Both check the Access token themselves before anything is read, and neither logs the
// token, an email or the read token.
//
// index.js is the entry point and exports one set of these handlers; tests build their own.
// See docs/architecture/decisions/0014-usage-measurement.md, 0015-behaviour-measurement.md and
// 0016-usage-admin-views.md.

import { ACCESS_HEADER, AccessRefused, createAccessCheck, teamHost } from "./access.js";
import { ADMIN_CONTRACT, analyticsUrl, buildReport, rangeRefusal, reportQuery, rowsFromAnswer } from "./report.js";
import {
  EVENT_VERSION,
  EVENT_VERSIONS,
  MARKER_HEADER,
  MARKER_VALUE,
  MAX_BODY_BYTES,
  RefusedError,
  SITE_ORIGIN,
  STATUS_CONTRACT,
  dataPoint,
  eventFrom,
} from "./rules.js";

const BASE_HEADERS = {
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  [MARKER_HEADER]: MARKER_VALUE,
};

/** Only the site's own origin is ever named back to a browser. */
const SITE_CORS = { "access-control-allow-origin": SITE_ORIGIN, vary: "Origin" };

const PREFLIGHT = {
  "access-control-allow-methods": "POST",
  "access-control-allow-headers": "content-type",
  "access-control-max-age": "86400",
};

/**
 * The report's answers are one signed-in person's and must not sit in any shared cache. They
 * carry no CORS header: the admin page is on the same origin.
 */
const PRIVATE = { "cache-control": "private, no-store" };

function json(body, status, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...BASE_HEADERS, ...headers },
  });
}

function empty(status, headers = {}) {
  return new Response(null, { status, headers: { ...BASE_HEADERS, ...headers } });
}

/** The route a request names: the events, the status, the report, the admin check, or nothing. */
export function routeFor(pathname) {
  if (pathname === "/api/v1/usage/events") return "events";
  if (pathname === "/api/v1/usage/status") return "status";
  if (pathname === "/api/v1/usage/report") return "report";
  if (pathname === "/api/v1/usage/report/me") return "report_me";
  return null;
}

/**
 * The four settings the report routes need, or null when any is missing: without all of them
 * the Worker can neither check a sign-in nor read the record.
 */
function reportSettings(env) {
  const text = (value) => (typeof value === "string" ? value.trim() : "");
  const settings = {
    host: teamHost(env.ACCESS_TEAM_DOMAIN),
    audience: text(env.ACCESS_AUD),
    accountId: text(env.ANALYTICS_ACCOUNT_ID),
    token: text(env.ANALYTICS_TOKEN),
  };
  return Object.values(settings).every((value) => value !== "") ? settings : null;
}

async function readEvent(request) {
  const length = Number(request.headers.get("content-length") ?? "0");
  if (length > MAX_BODY_BYTES) throw new RefusedError("body_too_large");
  const bytes = await request.arrayBuffer();
  if (bytes.byteLength > MAX_BODY_BYTES) throw new RefusedError("body_too_large");
  let body;
  try {
    body = JSON.parse(new TextDecoder().decode(bytes));
  } catch {
    throw new RefusedError("body_not_json");
  }
  return eventFrom(body);
}

function failure(error) {
  return { error: error instanceof Error ? error.name : "unknown" };
}

/**
 * The handler over the given log, fetch and clock; the tests hand in their own, and a fake
 * dataset and settings in `env`. The Access keys it reads are kept for the life of this handler,
 * which index.js makes once per isolate.
 */
export function createWorker(options = {}) {
  const log = options.log ?? ((event, fields) => console.log(JSON.stringify({ event, ...fields })));
  // Called through a wrapper: the runtime's fetch refuses to run detached from the global.
  const fetchImpl = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
  const now = options.now ?? (() => Date.now());
  const verifyAccess = createAccessCheck({ fetch: fetchImpl, now });

  async function events(request, env) {
    if (request.headers.get("origin") !== SITE_ORIGIN) {
      return json({ error: "origin_refused" }, 403);
    }
    if (request.method === "OPTIONS") return empty(204, { ...SITE_CORS, ...PREFLIGHT });
    if (request.method !== "POST") return json({ error: "method_not_allowed" }, 405, SITE_CORS);
    let event;
    try {
      event = await readEvent(request);
    } catch (error) {
      if (error instanceof RefusedError) return json({ error: error.reason }, 400, SITE_CORS);
      throw error;
    }
    try {
      env.USAGE_EVENTS.writeDataPoint(dataPoint(event));
    } catch (error) {
      log("write_failed", failure(error));
      return json({ error: "store_unavailable" }, 503, SITE_CORS);
    }
    return empty(204, SITE_CORS);
  }

  function status(request, env) {
    if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405);
    const bound = typeof env.USAGE_EVENTS?.writeDataPoint === "function";
    // `event_version` keeps naming version 1 for the readers that already know the field;
    // `event_versions` lists every version this Worker takes.
    return json(
      { contract_version: STATUS_CONTRACT, event_version: EVENT_VERSION, event_versions: EVENT_VERSIONS, bound },
      200,
    );
  }

  /**
   * The record for the range, or null when Analytics Engine did not answer with rows. Only the
   * status or the error's name is logged: the answer's body could echo the query or the token.
   */
  async function readReport(settings, from, to) {
    let response;
    try {
      response = await fetchImpl(analyticsUrl(settings.accountId), {
        method: "POST",
        headers: { authorization: `Bearer ${settings.token}` },
        body: reportQuery(from, to),
      });
    } catch (error) {
      log("analytics_failed", failure(error));
      return null;
    }
    if (!response.ok) {
      log("analytics_failed", { status: response.status });
      await response.body?.cancel();
      return null;
    }
    try {
      const { rows, truncated } = rowsFromAnswer(await response.json());
      return buildReport({ from, to, truncated, rows });
    } catch (error) {
      log("analytics_failed", failure(error));
      return null;
    }
  }

  async function report(request, env, route) {
    if (request.method !== "GET") return json({ error: "method_not_allowed" }, 405, PRIVATE);
    const settings = reportSettings(env);
    if (settings === null) return json({ error: "report_not_configured" }, 503, PRIVATE);
    try {
      await verifyAccess(request.headers.get(ACCESS_HEADER), settings);
    } catch (error) {
      if (!(error instanceof AccessRefused)) throw error;
      // The reason is a fixed word, so a wrong audience tag or team name shows in the logs
      // without the token or the person in it.
      log("access_refused", { reason: error.reason });
      return json({ error: "access_refused" }, 403, PRIVATE);
    }
    if (route === "report_me") return json({ contract_version: ADMIN_CONTRACT, admin: true }, 200, PRIVATE);
    const query = new URL(request.url).searchParams;
    const from = query.get("from");
    const to = query.get("to");
    const today = new Date(now()).toISOString().slice(0, 10);
    const refusal = rangeRefusal(from, to, today);
    if (refusal !== null) return json({ error: refusal }, 400, PRIVATE);
    const answer = await readReport(settings, from, to);
    if (answer === null) return json({ error: "analytics_unavailable" }, 502, PRIVATE);
    return json(answer, 200, PRIVATE);
  }

  return {
    async fetch(request, env = {}) {
      try {
        const route = routeFor(new URL(request.url).pathname);
        if (route === "events") return await events(request, env);
        if (route === "status") return status(request, env);
        if (route === "report" || route === "report_me") return await report(request, env, route);
        return json({ error: "no_such_route" }, 404);
      } catch (error) {
        log("request_failed", failure(error));
        return json({ error: "worker_failed" }, 500);
      }
    },
  };
}
