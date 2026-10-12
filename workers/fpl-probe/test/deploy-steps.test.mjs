// The deploy workflow's own steps, run with node --test. The workflow itself can only run
// against a Cloudflare account, so what it parses and what it accepts as a live probe are
// pinned here instead.

import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { describe, it } from "node:test";

import {
  NOW_URL,
  PLACEHOLDER,
  RESULTS_URL,
  confirmGone,
  judgeNow,
  namespaceId,
  namespacesFrom,
  probeUntil,
  showsGone,
  smoke,
  withNamespaceId,
} from "../scripts/deploy-steps.mjs";
import { MARKER_VALUE, NOW_HEADER_VALUE, PROBE_DAYS, PROBE_HEADER } from "../src/probe.js";

const ID = "0123456789abcdef0123456789abcdef";
const OTHER = "fedcba9876543210fedcba9876543210";
const REPOSITORY = new URL("../../../", import.meta.url);
const WORKFLOWS = new URL(".github/workflows/", REPOSITORY);

const quiet = { sleep: async () => {}, log: () => {} };

function listing(namespaces) {
  return `\n ⛅️ wrangler 4.123.0\n───────────────────\n${JSON.stringify(namespaces, null, 2)}\n`;
}

function answers(sequence) {
  const calls = [];
  const inits = [];
  const fetchImpl = async (url, init) => {
    calls.push(url);
    inits.push(init);
    const next = sequence.shift();
    if (next instanceof Error) throw next;
    return next;
  };
  return { calls, inits, fetchImpl };
}

/** An answer as the probe Worker sends it: JSON, marked with its header. */
function fromWorker(body, status = 200) {
  return Response.json(body, { status, headers: { [PROBE_HEADER]: MARKER_VALUE } });
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

describe("choosing when the probe stops", () => {
  it("is PROBE_DAYS after the deploy, as a time wrangler's --var keeps whole", () => {
    const deployed = Date.parse("2026-10-05T18:30:00.000Z");
    assert.equal(PROBE_DAYS, 7);
    const until = probeUntil(deployed);
    assert.equal(until, "2026-10-12T18:30:00.000Z");
    // wrangler splits `--var KEY:VALUE` at the first colon and joins the rest back.
    const [key, ...rest] = `PROBE_UNTIL:${until}`.split(":");
    assert.equal(key, "PROBE_UNTIL");
    assert.equal(rest.join(":"), until);
    assert.match(until, /^[0-9TZ:.-]+$/, "nothing a command line would split or expand");
    assert.throws(() => probeUntil(Number.NaN), /not a time/);
  });
});

describe("the smoke after a deploy", () => {
  it("passes on the probe's records whatever FPL answered, asking with the probe's header", async () => {
    const { calls, inits, fetchImpl } = answers([
      fromWorker({ records: [record, { ...record, status: null, error: "timeout" }] }),
    ]);
    const result = await smoke({ fetchImpl, ...quiet });
    assert.equal(result.ok, true);
    assert.deepEqual(calls, [NOW_URL]);
    assert.equal(new Headers(inits[0].headers).get(PROBE_HEADER), NOW_HEADER_VALUE);
  });

  it("fails at once when the Worker says the probe has ended", async () => {
    const { calls, fetchImpl } = answers([fromWorker({ error: "ended" }, 410)]);
    const result = await smoke({ fetchImpl, ...quiet });
    assert.equal(result.ok, false);
    assert.equal(calls.length, 1);
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
  it("passes once the results path answers without the Worker's marker", async () => {
    const { calls, fetchImpl } = answers([
      fromWorker({ records: [], summary: {} }),
      new Response("<!doctype html>", { headers: { "content-type": "text/html" } }),
    ]);
    assert.equal(await confirmGone({ fetchImpl, ...quiet }), true);
    assert.equal(calls.length, 2);
  });

  it("does not take the Worker's own errors, no answer, or Cloudflare's refusals as gone", async () => {
    const { calls, fetchImpl } = answers([
      fromWorker({ error: "internal" }, 500),
      fromWorker({ error: "not_found" }, 404),
      new TypeError("fetch failed"),
      new DOMException("The operation was aborted due to timeout", "TimeoutError"),
      new Response("rate limited", { status: 429 }),
      new Response("bad gateway", { status: 502 }),
    ]);
    assert.equal(await confirmGone({ fetchImpl, ...quiet }), false);
    assert.equal(calls.length, 6);
  });

  it("fails while the probe keeps answering", async () => {
    const stillThere = () => fromWorker({ records: [], summary: {} });
    const { fetchImpl } = answers([stillThere(), stillThere()]);
    assert.equal(await confirmGone({ fetchImpl, attempts: 2, ...quiet }), false);
  });

  it("reads gone only from an HTTP answer without the marker", () => {
    assert.equal(showsGone({ status: 200, marked: false }), true);
    assert.equal(showsGone({ status: 404, marked: false }), true);
    assert.equal(showsGone({ status: 200, marked: true }), false);
    assert.equal(showsGone({ status: null, marked: false }), false);
    assert.equal(showsGone({ status: 429, marked: false }), false);
    assert.equal(showsGone({ status: 503, marked: false }), false);
  });
});

describe("the workflows", () => {
  const TEST_FILE = /workers\/fpl-probe\/test\/[\w.-]+\.test\.mjs/g;

  /** A file's text with LF line ends, whatever the checkout wrote. */
  async function text(url) {
    return (await readFile(url, "utf8")).replace(/\r\n/g, "\n");
  }

  const workflowText = (name) => text(new URL(name, WORKFLOWS));

  it("run every probe test file, in CI, before a deploy, and in the web guide's list", async () => {
    const onDisk = (await readdir(new URL("./", import.meta.url)))
      .filter((name) => name.endsWith(".test.mjs"))
      .map((name) => `workers/fpl-probe/test/${name}`)
      .sort();
    for (const file of [
      new URL("ci.yml", WORKFLOWS),
      new URL("deploy-fpl-probe.yml", WORKFLOWS),
      new URL("web/README.md", REPOSITORY),
    ]) {
      const named = [...new Set((await text(file)).match(TEST_FILE))].sort();
      assert.deepEqual(named, onDisk, file.pathname);
    }
  });

  it("delete the Worker before anything that could stop the job, and the namespace last", async () => {
    const text = await workflowText("deploy-fpl-probe.yml");
    const step = (name) => {
      const at = text.indexOf(`- name: ${name}\n`);
      assert.notEqual(at, -1, name);
      return at;
    };
    const deleteWorker = step("Delete the probe Worker");
    assert.ok(deleteWorker < step("Confirm the probe no longer answers"));
    assert.ok(deleteWorker < step("List KV namespaces"));
    assert.ok(
      step("Confirm the probe no longer answers") < step("Delete the probe's KV namespace"),
    );
    assert.match(text, /command: delete --name squadopt-fpl-probe --force\n/);
    assert.match(
      text,
      /if: inputs\.action == 'delete' && steps\.confirm_gone\.outcome == 'success'/,
    );
    assert.match(
      text,
      /command: deploy --var PROBE_UNTIL:\$\{\{ steps\.until\.outputs\.until \}\}\n/,
    );
  });
});
