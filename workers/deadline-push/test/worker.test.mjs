// The Worker over a fake world: the two routes, and a scheduled run that reminds each
// subscriber once of the week whose deadline is three hours away, drops a gone subscription,
// and sends nothing between deadlines.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import entryPoint from "../src/index.js";
import { KEY_CONTRACT, MARKER_HEADER, MARKER_VALUE, REMIND_BEFORE_MS, SCHEDULE_URL } from "../src/rules.js";
import { memoryStore } from "../src/store.js";
import { createWorker, routeFor } from "../src/worker.js";
import {
  GW11_DEADLINE,
  NOW_MS,
  SITE,
  decryptMessage,
  fakeFetch,
  fixturesJson,
  subscriber,
  testClock,
  vapidPair,
} from "./support.mjs";

async function harness({ start = NOW_MS, ...world } = {}) {
  const clock = testClock(start);
  const store = memoryStore();
  const upstream = fakeFetch(world);
  const lines = [];
  const vapid = await vapidPair();
  const env = {
    VAPID_PUBLIC_KEY: vapid.publicKey,
    VAPID_PRIVATE_KEY: vapid.privateKey,
    VAPID_SUBJECT: "https://squadopt.mymandev.com",
  };
  const worker = createWorker({
    fetch: upstream.fetchImpl,
    now: clock.now,
    store,
    log: (event, fields) => lines.push({ event, ...fields }),
  });
  const send = async (method, path, body) => {
    const response = await worker.fetch(
      new Request(`${SITE}${path}`, {
        method,
        headers: body === undefined ? {} : { "content-type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      }),
      env,
    );
    const text = await response.text();
    return { response, body: text === "" ? null : JSON.parse(text) };
  };
  return { clock, store, upstream, lines, worker, env, vapid, send };
}

describe("the routes", () => {
  it("names its two paths and nothing else under the prefix", () => {
    assert.equal(routeFor("/api/v1/push/key"), "key");
    assert.equal(routeFor("/api/v1/push/subscriptions"), "subscriptions");
    assert.equal(routeFor("/api/v1/push/"), null);
    assert.equal(routeFor("/api/v1/push/smoke"), null);
    assert.equal(routeFor("/api/v1/fpl/standings/1"), null);
  });

  it("answers the key as a marked JSON document, and GET only", async () => {
    const { send, vapid } = await harness();
    const { response, body } = await send("GET", "/api/v1/push/key");
    assert.equal(response.status, 200);
    assert.equal(response.headers.get(MARKER_HEADER), MARKER_VALUE);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.deepEqual(body, { contract_version: KEY_CONTRACT, public_key: vapid.publicKey });
    assert.equal((await send("POST", "/api/v1/push/key")).response.status, 405);
  });

  it("gives a path under the prefix that is neither route its JSON 404", async () => {
    const { send } = await harness();
    const { response, body } = await send("GET", "/api/v1/push/smoke");
    assert.equal(response.status, 404);
    assert.equal(response.headers.get(MARKER_HEADER), MARKER_VALUE);
    assert.deepEqual(body, { error: "no_such_route" });
  });

  it("keeps a subscription on PUT, once per endpoint, and drops it on DELETE", async () => {
    const { send, store, lines } = await harness();
    const who = await subscriber();
    assert.equal((await send("PUT", "/api/v1/push/subscriptions", who.body)).response.status, 204);
    assert.equal(await store.count(), 1);
    // The same endpoint again with a new language replaces the row rather than adding one.
    assert.equal((await send("PUT", "/api/v1/push/subscriptions", { ...who.body, language: "en" })).response.status, 204);
    assert.equal(await store.count(), 1);
    assert.equal([...store.rows.values()][0].language, "en");
    assert.deepEqual(lines.map((line) => line.event), ["subscribed", "subscribed"]);
    assert.equal(lines[0].league, true);
    assert.equal((await send("DELETE", "/api/v1/push/subscriptions", { endpoint: who.body.endpoint })).response.status, 204);
    assert.equal(await store.count(), 0);
    // Removing what is not there is still a 204: the browser's state is what matters.
    assert.equal((await send("DELETE", "/api/v1/push/subscriptions", { endpoint: who.body.endpoint })).response.status, 204);
  });

  it("refuses a request it cannot read, naming the reason, and keeps nothing of it", async () => {
    const { send, store, worker, env } = await harness();
    const who = await subscriber();
    const refused = await send("PUT", "/api/v1/push/subscriptions", { ...who.body, language: "fr" });
    assert.equal(refused.response.status, 400);
    assert.deepEqual(refused.body, { error: "language_refused" });
    const notJson = await worker.fetch(
      new Request(`${SITE}/api/v1/push/subscriptions`, { method: "PUT", body: "{" }),
      env,
    );
    assert.equal(notJson.status, 400);
    assert.deepEqual(await notJson.json(), { error: "body_not_json" });
    const tooLarge = await worker.fetch(
      new Request(`${SITE}/api/v1/push/subscriptions`, { method: "PUT", body: "x".repeat(5000) }),
      env,
    );
    assert.deepEqual(await tooLarge.json(), { error: "body_too_large" });
    assert.equal((await send("PATCH", "/api/v1/push/subscriptions", {})).response.status, 405);
    assert.equal(await store.count(), 0);
  });

  it("answers 503 when the store fails, and logs the failure without the request", async () => {
    const upstream = fakeFetch();
    const lines = [];
    const worker = createWorker({
      fetch: upstream.fetchImpl,
      store: { upsert: async () => { throw new Error("D1 is away"); } },
      log: (event, fields) => lines.push({ event, ...fields }),
    });
    const who = await subscriber();
    const response = await worker.fetch(
      new Request(`${SITE}/api/v1/push/subscriptions`, { method: "PUT", body: JSON.stringify(who.body) }),
      {},
    );
    assert.equal(response.status, 503);
    assert.deepEqual(lines, [{ event: "store_failed", error: "Error: D1 is away" }]);
  });
});

describe("a scheduled run", () => {
  it("reminds each subscriber once of the week three hours away, in their language, and not again", async () => {
    const { send, worker, env, upstream, store, lines, clock } = await harness();
    const tr = await subscriber("tr");
    const en = await subscriber("en", { language: "en", league_id: 0, entry_id: 542322 });
    await send("PUT", "/api/v1/push/subscriptions", tr.body);
    await send("PUT", "/api/v1/push/subscriptions", en.body);
    // Ten minutes outside the window: the fixture list is read, nothing is sent.
    await worker.scheduled({ cron: "*/15 * * * *" }, env, { waitUntil() {} });
    assert.deepEqual(upstream.calls, [SCHEDULE_URL]);
    assert.deepEqual(lines.at(-1), { event: "reminded", gameweek: null, sent: 0, gone: 0, failed: 0 });

    clock.advance(10 * 60_000 + 1);
    await worker.scheduled({ cron: "*/15 * * * *" }, env, { waitUntil() {} });
    assert.equal(upstream.pushes.length, 2);
    assert.deepEqual(lines.at(-1), { event: "reminded", gameweek: 11, sent: 2, gone: 0, failed: 0 });
    const byUrl = Object.fromEntries(upstream.pushes.map((push) => [push.url, push]));
    const first = byUrl[tr.body.endpoint];
    assert.equal(first.headers["content-encoding"], "aes128gcm");
    assert.equal(first.headers.ttl, String(3 * 3600));
    assert.match(first.headers.authorization, /^vapid t=[^,]+, k=/);
    assert.deepEqual(JSON.parse((await decryptMessage(first.body, tr)).text), {
      title: "GW11: son 3 saat",
      body: "Planın hazır.",
      url: `${SITE}/league/352490/members/35249001`,
      gameweek: 11,
    });
    assert.deepEqual(JSON.parse((await decryptMessage(byUrl[en.body.endpoint].body, en)).text), {
      title: "GW11: 3 hours left",
      body: "Your plan is ready.",
      url: `${SITE}/entry/542322`,
      gameweek: 11,
    });
    for (const row of store.rows.values()) assert.equal(row.last_sent_gameweek, 11);

    // A quarter hour later, still inside the window: nobody is reminded twice.
    clock.advance(15 * 60_000);
    await worker.scheduled({ cron: "*/15 * * * *" }, env, { waitUntil() {} });
    assert.equal(upstream.pushes.length, 2);
    assert.deepEqual(lines.at(-1), { event: "reminded", gameweek: 11, sent: 0, gone: 0, failed: 0 });
    // No log line carries an endpoint.
    assert.equal(JSON.stringify(lines).includes("push.example.net"), false);
  });

  it("drops a subscription the push service says is gone, and keeps one it refused for now", async () => {
    const { send, worker, env, store, lines, clock } = await harness({
      start: Date.parse(GW11_DEADLINE) - REMIND_BEFORE_MS + 1,
      pushStatus: (request) => (request.url.endsWith("/gone") ? 410 : request.url.endsWith("/busy") ? 429 : 201),
    });
    for (const suffix of ["ok", "gone", "busy"]) {
      await send("PUT", "/api/v1/push/subscriptions", (await subscriber(suffix)).body);
    }
    await worker.scheduled({ cron: "*/15 * * * *" }, env, { waitUntil() {} });
    assert.deepEqual(lines.at(-1), { event: "reminded", gameweek: 11, sent: 1, gone: 1, failed: 1 });
    assert.equal(await store.count(), 2);
    assert.deepEqual(lines.filter((line) => line.event === "push_refused"), [{ event: "push_refused", status: 429 }]);
    // The refused one is tried again next run; the sent one is not.
    clock.advance(15 * 60_000);
    await worker.scheduled({ cron: "*/15 * * * *" }, env, { waitUntil() {} });
    assert.deepEqual(lines.at(-1), { event: "reminded", gameweek: 11, sent: 0, gone: 0, failed: 1 });
  });

  it("logs a run the fixture list fails, and sends nothing", async () => {
    const { send, worker, env, upstream, lines } = await harness({ fixturesStatus: 503 });
    await send("PUT", "/api/v1/push/subscriptions", (await subscriber()).body);
    await worker.scheduled({ cron: "*/15 * * * *" }, env, { waitUntil() {} });
    assert.equal(upstream.pushes.length, 0);
    assert.deepEqual(lines.at(-1), { event: "run_failed", error: "RefusedError: fixtures_status_503" });
  });

  it("reads the site's own fixture list and never FPL", async () => {
    const { worker, env, upstream } = await harness();
    await worker.scheduled({ cron: "*/15 * * * *" }, env, { waitUntil() {} });
    assert.deepEqual(upstream.calls, [`${SITE}/data/fixtures.json`]);
    assert.deepEqual(fixturesJson().payload.gameweeks.map((w) => w.gameweek), [10, 11, 12]);
  });
});

describe("the entry point", () => {
  it("exports the two handlers the runtime reads", () => {
    assert.equal(typeof entryPoint.fetch, "function");
    assert.equal(typeof entryPoint.scheduled, "function");
    assert.deepEqual(Object.keys(entryPoint).sort(), ["fetch", "scheduled"]);
  });
});
