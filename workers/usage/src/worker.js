// The usage Worker: one route takes an event from the site's pages and writes it to Analytics
// Engine, one says whether the Worker is bound to its dataset. It reads no address and no
// cookie, keeps nothing of its own, and logs nothing of what a page sent.
//
// index.js is the entry point and exports one set of these handlers; tests build their own.
// See docs/architecture/decisions/0014-usage-measurement.md.

import {
  EVENT_VERSION,
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

function json(body, status, headers = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...BASE_HEADERS, ...headers },
  });
}

function empty(status, headers = {}) {
  return new Response(null, { status, headers: { ...BASE_HEADERS, ...headers } });
}

/** The route a request names: the events, the status, or nothing under the prefix. */
export function routeFor(pathname) {
  if (pathname === "/api/v1/usage/events") return "events";
  if (pathname === "/api/v1/usage/status") return "status";
  return null;
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

/** The handler over the given log; the tests hand in their own and a fake dataset in `env`. */
export function createWorker(options = {}) {
  const log = options.log ?? ((event, fields) => console.log(JSON.stringify({ event, ...fields })));

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
    return json({ contract_version: STATUS_CONTRACT, event_version: EVENT_VERSION, bound }, 200);
  }

  return {
    async fetch(request, env = {}) {
      try {
        const route = routeFor(new URL(request.url).pathname);
        if (route === "events") return await events(request, env);
        if (route === "status") return status(request, env);
        return json({ error: "no_such_route" }, 404);
      } catch (error) {
        log("request_failed", failure(error));
        return json({ error: "worker_failed" }, 500);
      }
    },
  };
}
