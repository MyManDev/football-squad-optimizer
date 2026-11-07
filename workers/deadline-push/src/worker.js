// The deadline reminder Worker: two handlers. `fetch` keeps and drops push subscriptions under
// /api/v1/push/ on the site's host; `scheduled` runs every quarter hour, reads the site's own
// fixture list, and when a deadline is within three hours sends each subscriber one
// notification for that gameweek. Nothing about a visitor is kept but the subscription itself.
//
// index.js is the entry point and exports one set of these handlers; tests build their own.
// See docs/architecture/decisions/0013-deadline-reminders.md.

import {
  KEY_CONTRACT,
  MARKER_HEADER,
  MARKER_VALUE,
  MAX_BODY_BYTES,
  PUSH_TTL_SECONDS,
  RefusedError,
  SCHEDULE_URL,
  deadlinesFrom,
  endpointFrom,
  payloadFor,
  subscriptionFrom,
  subscriptionGone,
  windowGameweek,
} from "./rules.js";
import { d1Store } from "./store.js";
import { importVapidKey, pushRequest } from "./webpush.js";

const JSON_HEADERS = {
  "content-type": "application/json; charset=utf-8",
  "cache-control": "no-store",
  "x-content-type-options": "nosniff",
  [MARKER_HEADER]: MARKER_VALUE,
};

/** How many subscribers one run reminds; the next run takes the rest. */
export const BATCH = 500;

/** The Worker gives up on a push service that does not answer in this time. */
export const PUSH_TIMEOUT_MS = 10_000;

/** The site's fixture list is read with this much patience. */
const SCHEDULE_TIMEOUT_MS = 8_000;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: JSON_HEADERS });
}

function empty(status) {
  return new Response(null, { status, headers: JSON_HEADERS });
}

function refusal(status, reason) {
  return json({ error: reason }, status);
}

function failure(error) {
  return { error: error instanceof Error ? `${error.name}: ${error.message}` : String(error) };
}

/** The route a request names: the key, the subscriptions, or nothing under the prefix. */
export function routeFor(pathname) {
  if (pathname === "/api/v1/push/key") return "key";
  if (pathname === "/api/v1/push/subscriptions") return "subscriptions";
  return null;
}

async function readBody(request) {
  const length = Number(request.headers.get("content-length") ?? "0");
  if (length > MAX_BODY_BYTES) throw new RefusedError("body_too_large");
  const text = await request.text();
  if (text.length > MAX_BODY_BYTES) throw new RefusedError("body_too_large");
  try {
    return JSON.parse(text);
  } catch {
    throw new RefusedError("body_not_json");
  }
}

/**
 * The handlers over the given reads and clock. `fetch` and `now` are replaced by the tests;
 * `store` is read from the D1 binding when the tests do not hand one in.
 */
export function createWorker(options = {}) {
  const now = options.now ?? (() => Date.now());
  const fetchImpl = options.fetch ?? ((input, init) => globalThis.fetch(input, init));
  const log = options.log ?? ((event, fields) => console.log(JSON.stringify({ event, ...fields })));
  const randomness = options.randomness ?? crypto;
  const storeOf = (env) => options.store ?? d1Store(env.PUSH_DB);

  async function handle(request, env) {
    const url = new URL(request.url);
    const route = routeFor(url.pathname);
    if (route === null) return refusal(404, "no_such_route");
    if (route === "key") {
      if (request.method !== "GET") return refusal(405, "method_not_allowed");
      return json({ contract_version: KEY_CONTRACT, public_key: env.VAPID_PUBLIC_KEY });
    }
    const store = storeOf(env);
    try {
      if (request.method === "PUT") {
        const subscription = subscriptionFrom(await readBody(request));
        await store.upsert(subscription, new Date(now()).toISOString());
        log("subscribed", { league: subscription.league_id > 0 });
        return empty(204);
      }
      if (request.method === "DELETE") {
        const removed = await store.remove(endpointFrom(await readBody(request)));
        log("unsubscribed", { removed });
        return empty(204);
      }
      return refusal(405, "method_not_allowed");
    } catch (error) {
      if (error instanceof RefusedError) return refusal(400, error.reason);
      log("store_failed", failure(error));
      return refusal(503, "store_unavailable");
    }
  }

  async function readDeadlines() {
    const response = await fetchImpl(SCHEDULE_URL, {
      headers: { accept: "application/json" },
      signal: AbortSignal.timeout(SCHEDULE_TIMEOUT_MS),
    });
    if (!response.ok) throw new RefusedError(`fixtures_status_${response.status}`);
    return deadlinesFrom(await response.json());
  }

  /** One run: the due gameweek, if any, and one message to each subscriber not yet reminded of it. */
  async function remind(env) {
    const nowMs = now();
    const due = windowGameweek(await readDeadlines(), nowMs);
    if (due === null) return { gameweek: null, sent: 0, gone: 0, failed: 0 };
    const store = storeOf(env);
    const vapid = {
      signingKey: await importVapidKey(env.VAPID_PRIVATE_KEY, env.VAPID_PUBLIC_KEY),
      publicKey: env.VAPID_PUBLIC_KEY,
      subject: env.VAPID_SUBJECT,
    };
    const counts = { gameweek: due.gameweek, sent: 0, gone: 0, failed: 0 };
    for (const subscription of await store.due(due.gameweek, BATCH)) {
      const payload = JSON.stringify(payloadFor(due.gameweek, subscription));
      try {
        const request = await pushRequest({
          subscription,
          payload,
          vapid,
          nowMs,
          ttlSeconds: PUSH_TTL_SECONDS,
          randomness,
        });
        const response = await fetchImpl(request, { signal: AbortSignal.timeout(PUSH_TIMEOUT_MS) });
        if (response.ok) {
          await store.markSent(subscription.id, due.gameweek);
          counts.sent += 1;
        } else if (subscriptionGone(response.status)) {
          await store.removeById(subscription.id);
          counts.gone += 1;
        } else {
          counts.failed += 1;
          log("push_refused", { status: response.status });
        }
      } catch (error) {
        counts.failed += 1;
        log("push_failed", failure(error));
      }
    }
    return counts;
  }

  return {
    async fetch(request, env = {}) {
      try {
        return await handle(request, env);
      } catch (error) {
        log("request_failed", failure(error));
        return refusal(500, "worker_failed");
      }
    },
    async scheduled(_event, env = {}, ctx) {
      const run = remind(env)
        .then((counts) => log("reminded", counts))
        .catch((error) => log("run_failed", failure(error)));
      if (ctx?.waitUntil) ctx.waitUntil(run);
      await run;
    },
    remind,
  };
}
