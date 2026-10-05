// The deploy workflow's own steps, run with node --test. The workflow itself can only run
// against a Cloudflare account, so what it parses and what it accepts as a live probe are
// pinned here instead.

import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { describe, it } from "node:test";

import {
  NOW_URL,
  PLACEHOLDER,
  RESULTS_URL,
  confirmGone,
  judgeNow,
  namespaceId,
  namespacesFrom,
  smoke,
  withNamespaceId,
} from "../scripts/deploy-steps.mjs";

const ID = "0123456789abcdef0123456789abcdef";
const OTHER = "fedcba9876543210fedcba9876543210";

const quiet = { sleep: async () => {}, log: () => {} };

function listing(namespaces) {
  return `\n ⛅️ wrangler 4.123.0\n───────────────────\n${JSON.stringify(namespaces, null, 2)}\n`;
}

function answers(sequence) {
  const calls = [];
  const fetchImpl = async (url) => {
    calls.push(url);
    const next = sequence.shift();
    if (next instanceof Error) throw next;
    return next;
  };
  return { calls, fetchImpl };
}

const record = { at: "2026-10-05T12:00:00.000Z", target: "https://x/", status: 403 };

describe("finding the probe's KV namespace", () => {
  it("reads wrangler's listing past its banner", () => {
    const text = listing([
      { id: OTHER, title: "something-else" },
      { id: ID, title: "squadopt-fpl-probe" },
    ]);
    assert.equal(namespacesFrom(text).length, 2);
    assert.equal(namespaceId(text), ID);
  });

  it("says there is none rather than guessing", () => {
    assert.equal(namespaceId(listing([])), null);
    assert.equal(namespaceId(listing([{ id: OTHER, title: "squadopt-fpl-probe-preview" }])), null);
  });

  it("refuses two namespaces of the same title and a listing that is not JSON", () => {
    const twice = listing([
      { id: ID, title: "squadopt-fpl-probe" },
      { id: OTHER, title: "squadopt-fpl-probe" },
    ]);
    assert.throws(() => namespaceId(twice), /2 KV namespaces/);
    assert.throws(() => namespaceId("Authentication error [code: 10000]"), /no JSON array/);
    assert.throws(() => namespaceId(""), /no JSON array/);
  });
});

describe("writing the id into wrangler.toml", () => {
  it("replaces the committed placeholder exactly once", async () => {
    const config = await readFile(new URL("../wrangler.toml", import.meta.url), "utf8");
    const filled = withNamespaceId(config, ID);
    assert.ok(filled.includes(`id = "${ID}"`));
    assert.ok(!filled.includes(PLACEHOLDER));
    assert.equal(filled.replace(`id = "${ID}"`, `id = "${PLACEHOLDER}"`), config);
  });

  it("refuses a missing id and a file already filled in", async () => {
    const config = await readFile(new URL("../wrangler.toml", import.meta.url), "utf8");
    assert.throws(() => withNamespaceId(config, ""), /expected shape/);
    assert.throws(() => withNamespaceId(config, "not-an-id"), /expected shape/);
    assert.throws(() => withNamespaceId(withNamespaceId(config, ID), OTHER), /holds 0/);
  });
});

describe("the smoke after a deploy", () => {
  it("passes on the probe's records whatever FPL answered", async () => {
    const { calls, fetchImpl } = answers([
      Response.json({ records: [record, { ...record, status: null, error: "timeout" }] }),
    ]);
    const result = await smoke({ fetchImpl, ...quiet });
    assert.equal(result.ok, true);
    assert.deepEqual(calls, [NOW_URL]);
  });

  it("waits while the site's shell still answers the path, then passes", async () => {
    const shell = () =>
      new Response("<!doctype html><title>SquadOpt</title>", {
        headers: { "content-type": "text/html" },
      });
    const { calls, fetchImpl } = answers([
      shell(),
      new TypeError("fetch failed"),
      Response.json({ records: [record] }),
    ]);
    const result = await smoke({ fetchImpl, ...quiet });
    assert.equal(result.ok, true);
    assert.equal(calls.length, 3);
  });

  it("accepts the once-a-minute gate when the stored results are the probe's", async () => {
    const { calls, fetchImpl } = answers([
      Response.json({ error: "too_many_requests", retry_after_seconds: 30 }, { status: 429 }),
      Response.json({ records: [record], summary: { probes: 1 } }),
    ]);
    const result = await smoke({ fetchImpl, ...quiet });
    assert.equal(result.ok, true);
    assert.deepEqual(calls, [NOW_URL, RESULTS_URL]);
  });

  it("fails when the Worker never answers with its JSON", async () => {
    const notFound = () => Response.json({ error: "not_found" }, { status: 404 });
    const { calls, fetchImpl } = answers([notFound(), notFound(), notFound()]);
    const result = await smoke({ fetchImpl, attempts: 3, ...quiet });
    assert.equal(result.ok, false);
    assert.equal(calls.length, 3);
  });

  it("does not count an error from the Worker as the probe answering", () => {
    const unavailable = { status: 503, body: { error: "unavailable" } };
    assert.equal(judgeNow(unavailable), null);
    assert.equal(judgeNow({ status: 200, body: { records: [{ at: "x" }] } }), null);
    assert.equal(judgeNow({ status: 200, body: { records: [] } }), null);
    assert.equal(judgeNow({ status: 200, body: { records: [record] } }), "records");
  });
});

describe("the check after a delete", () => {
  it("passes once the results path stops answering as the probe", async () => {
    const { calls, fetchImpl } = answers([
      Response.json({ records: [], summary: {} }),
      new Response("<!doctype html>", { headers: { "content-type": "text/html" } }),
    ]);
    assert.equal(await confirmGone({ fetchImpl, ...quiet }), true);
    assert.equal(calls.length, 2);
  });

  it("fails while the probe keeps answering", async () => {
    const stillThere = () => Response.json({ records: [], summary: {} });
    const { fetchImpl } = answers([stillThere(), stillThere()]);
    assert.equal(await confirmGone({ fetchImpl, attempts: 2, ...quiet }), false);
  });
});
