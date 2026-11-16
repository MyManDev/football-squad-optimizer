// The Worker over a fake dataset: what it writes, what it refuses, and which origins it answers.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import entryPoint from "../src/index.js";
import { KINDS, MARKER_HEADER, MARKER_VALUE, MAX_BODY_BYTES, STATUS_CONTRACT } from "../src/rules.js";
import { routeFor } from "../src/worker.js";
import { SESSION, SITE, goodBehaviour, goodEvent, harness } from "./support.mjs";

const EVENTS = "/api/v1/usage/events";
const allowed = (response) => response.headers.get("access-control-allow-origin");

describe("the routes", () => {
  it("names its two paths and nothing else under the prefix", () => {
    assert.equal(routeFor(EVENTS), "events");
    assert.equal(routeFor("/api/v1/usage/status"), "status");
    assert.equal(routeFor("/api/v1/usage/"), null);
    assert.equal(routeFor("/api/v1/usage/events/1"), null);
  });

  it("answers anything else with its own marked 404", async () => {
    const { send } = harness();
    const response = await send("/api/v1/usage/nothing", { method: "GET" });
    assert.equal(response.status, 404);
    assert.equal(response.headers.get(MARKER_HEADER), MARKER_VALUE);
  });

  it("exports only the fetch handler", () => {
    assert.deepEqual(Object.keys(entryPoint), ["fetch"]);
  });
});

describe("an event from the site", () => {
  it("is written once and answered with nothing, as a beacon's text/plain body", async () => {
    const { send, written } = harness();
    const response = await send(EVENTS, {
      body: JSON.stringify(goodEvent()),
      headers: { "content-type": "text/plain;charset=UTF-8" },
    });
    assert.equal(response.status, 204);
    assert.equal(allowed(response), SITE);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(written.length, 1);
    assert.deepEqual(written[0].indexes, [SESSION]);
  });

  it("writes nothing of the request but the event", async () => {
    const { send, written } = harness();
    await send(EVENTS, {
      body: JSON.stringify(goodEvent()),
      headers: { "cf-connecting-ip": "203.0.113.9", "user-agent": "Mozilla/5.0 fingerprint", cookie: "a=b" },
    });
    const stored = JSON.stringify(written);
    for (const text of ["203.0.113.9", "fingerprint", "a=b"]) assert.equal(stored.includes(text), false, text);
  });

  it("is refused, and written nowhere, when it breaks a rule", async () => {
    const { send, written } = harness();
    const cases = [
      ["not json", "body_not_json"],
      [JSON.stringify(goodEvent({ page: "/league/1" })), "page_refused"],
      [JSON.stringify({ ...goodEvent(), entry_id: 1 }), "wrong_fields"],
    ];
    for (const [body, reason] of cases) {
      const response = await send(EVENTS, { body });
      assert.equal(response.status, 400);
      assert.deepEqual(await response.json(), { error: reason });
    }
    assert.equal(written.length, 0);
  });

  it("is refused above the size cap, by header and by the bytes themselves", async () => {
    const { send, written } = harness();
    const big = "x".repeat(MAX_BODY_BYTES + 1);
    const byHeader = await send(EVENTS, { body: big, headers: { "content-length": String(big.length) } });
    assert.equal(byHeader.status, 400);
    assert.deepEqual(await byHeader.json(), { error: "body_too_large" });
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(big));
        controller.close();
      },
    });
    const worker = harness();
    const response = await worker.worker.fetch(
      new Request(`${SITE}${EVENTS}`, { method: "POST", headers: { origin: SITE }, body: stream, duplex: "half" }),
      worker.env,
    );
    assert.equal(response.status, 400);
    assert.deepEqual(await response.json(), { error: "body_too_large" });
    assert.equal(written.length + worker.written.length, 0);
  });

  it("answers 503 and logs only the error's name when the dataset fails", async () => {
    const { send, lines } = harness({
      dataset: {
        writeDataPoint() {
          throw new TypeError(`the event was ${SESSION}`);
        },
      },
    });
    const response = await send(EVENTS, { body: JSON.stringify(goodEvent()) });
    assert.equal(response.status, 503);
    assert.deepEqual(lines, [{ event: "write_failed", error: "TypeError" }]);
  });

  it("answers 405 to any other method", async () => {
    const { send } = harness();
    assert.equal((await send(EVENTS, { method: "GET" })).status, 405);
    assert.equal((await send(EVENTS, { method: "PUT", body: "{}" })).status, 405);
  });
});

describe("a version 2 event from the site", () => {
  it("is written once for every kind, in the kind's columns, and answered with nothing", async () => {
    const { send, written } = harness();
    for (const kind of KINDS) {
      const response = await send(EVENTS, {
        body: JSON.stringify(goodBehaviour(kind)),
        headers: { "content-type": "text/plain;charset=UTF-8" },
      });
      assert.equal(response.status, 204, kind);
      assert.equal(allowed(response), SITE);
    }
    assert.equal(written.length, KINDS.size);
    for (const point of written) {
      assert.deepEqual(point.indexes, [SESSION]);
      assert.equal(point.blobs.length, 9);
      assert.equal(point.doubles[0], 2);
    }
    assert.deepEqual(
      written.map((point) => [point.blobs[2], ...point.blobs.slice(6), point.doubles[1]]),
      [
        ["click", "decision", "control", "none", 47],
        ["scroll", "s30", "", "", 60],
        ["vital", "lcp", "good", "", 1840],
        ["error", "chunk", "", "", 0],
        ["arrival", "whatsapp", "last_week", "", 0],
      ],
    );
  });

  it("is written beside version 1 events, each in its own layout", async () => {
    const { send, written } = harness();
    await send(EVENTS, { body: JSON.stringify(goodEvent()) });
    await send(EVENTS, { body: JSON.stringify(goodBehaviour("click")) });
    assert.deepEqual(written[0], {
      indexes: [SESSION],
      blobs: ["member", "what-if", "tool", "tr", "phone", SESSION],
      doubles: [1],
    });
    assert.equal(written[1].blobs.length, 9);
  });

  it("is refused, and written nowhere, when it breaks a rule", async () => {
    const { send, written } = harness();
    const cases = [
      [goodBehaviour("click", { zone: "/league/352490/members/35249001" }), "zone_refused"],
      [goodBehaviour("click", { cell: 400 }), "cell_refused"],
      [goodBehaviour("click", { cell: 12.5 }), "cell_refused"],
      [goodBehaviour("click", { x: 120 }), "wrong_fields"],
      [goodBehaviour("scroll", { depth: 55 }), "depth_refused"],
      [goodBehaviour("scroll", { dwell: "12 seconds" }), "dwell_refused"],
      [goodBehaviour("vital", { value: 60001 }), "value_refused"],
      [goodBehaviour("vital", { metric: "fid" }), "metric_refused"],
      [goodBehaviour("error", { error: "TypeError: x is undefined" }), "error_refused"],
      [goodBehaviour("error", { message: "boom" }), "wrong_fields"],
      [goodBehaviour("arrival", { source: "https://t.co/abc" }), "source_refused"],
      [goodBehaviour("arrival", { visit: "2026-W46" }), "visit_refused"],
      [goodBehaviour("arrival", { kind: "pageview" }), "kind_refused"],
      [goodBehaviour("arrival", { step: "open" }), "wrong_fields"],
      [goodBehaviour("arrival", { v: 3 }), "wrong_version"],
    ];
    for (const [body, reason] of cases) {
      const response = await send(EVENTS, { body: JSON.stringify(body) });
      assert.equal(response.status, 400, reason);
      assert.deepEqual(await response.json(), { error: reason });
      assert.equal(allowed(response), SITE);
    }
    assert.equal(written.length, 0);
  });

  it("is refused from another origin", async () => {
    const { send, written } = harness();
    const response = await send(EVENTS, { origin: "https://evil.example", body: JSON.stringify(goodBehaviour("click")) });
    assert.equal(response.status, 403);
    assert.equal(written.length, 0);
  });
});

describe("the origin rule", () => {
  it("refuses another origin and a request with none, naming no origin back", async () => {
    const { send, written } = harness();
    for (const origin of ["https://evil.example", "https://squadopt.pages.dev", "http://squadopt.mymandev.com", null]) {
      const response = await send(EVENTS, { origin, body: JSON.stringify(goodEvent()) });
      assert.equal(response.status, 403, String(origin));
      assert.equal(allowed(response), null);
    }
    assert.equal(written.length, 0);
  });

  it("answers the site's preflight and no one else's", async () => {
    const { send } = harness();
    const preflight = await send(EVENTS, { method: "OPTIONS" });
    assert.equal(preflight.status, 204);
    assert.equal(allowed(preflight), SITE);
    assert.equal(preflight.headers.get("access-control-allow-methods"), "POST");
    assert.equal(preflight.headers.get("vary"), "Origin");
    const other = await send(EVENTS, { method: "OPTIONS", origin: "https://evil.example" });
    assert.equal(other.status, 403);
    assert.equal(allowed(other), null);
  });
});

describe("the status route", () => {
  it("says the dataset is bound, and says so when it is not", async () => {
    const { send, worker } = harness();
    const response = await send("/api/v1/usage/status", { method: "GET", origin: null });
    assert.equal(response.status, 200);
    assert.deepEqual(await response.json(), {
      contract_version: STATUS_CONTRACT,
      event_version: 1,
      event_versions: [1, 2],
      bound: true,
    });
    const unbound = await worker.fetch(new Request(`${SITE}/api/v1/usage/status`), {});
    assert.equal((await unbound.json()).bound, false);
  });

  it("takes only GET", async () => {
    const { send } = harness();
    assert.equal((await send("/api/v1/usage/status", { body: "{}" })).status, 405);
  });
});
