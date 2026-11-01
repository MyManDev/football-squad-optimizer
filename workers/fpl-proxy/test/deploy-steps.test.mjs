// The deploy workflow's own steps, run with node --test. The workflow itself can only run
// against a Cloudflare account, so what it accepts as the forwarder answering, what it accepts
// as the forwarder gone, and what the workflow file says are pinned here instead.

import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { describe, it } from "node:test";

import {
  SMOKE_URL,
  confirmGone,
  isForwarderNotFound,
  showsGone,
  smoke,
} from "../scripts/deploy-steps.mjs";
import { MARKER_HEADER, MARKER_VALUE, routeFor } from "../src/proxy.js";
import { createWorker } from "../src/worker.js";

const REPOSITORY = new URL("../../../", import.meta.url);
const WORKFLOWS = new URL(".github/workflows/", REPOSITORY);

const quiet = { sleep: async () => {}, log: () => {} };

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

/** An answer as the forwarder sends it: JSON, marked with its header. */
function fromWorker(body, status = 200) {
  return Response.json(body, { status, headers: { [MARKER_HEADER]: MARKER_VALUE } });
}

const shell = () =>
  new Response("<!doctype html><title>SquadOpt</title>", {
    headers: { "content-type": "text/html" },
  });

/** A file's text with LF line ends, whatever the checkout wrote. */
async function text(url) {
  return (await readFile(url, "utf8")).replace(/\r\n/g, "\n");
}

describe("the smoke after a deploy", () => {
  it("asks a path under the route that is none of the routes, so FPL is asked nothing", () => {
    const url = new URL(SMOKE_URL);
    assert.equal(url.origin, "https://squadopt.mymandev.com");
    assert.ok(url.pathname.startsWith("/api/v1/fpl/"));
    assert.equal(routeFor("GET", url).status, 404);
  });

  it("passes on the forwarder's own JSON 404, which the real handler gives", async () => {
    const worker = createWorker({
      fetch: async (url) => {
        throw new Error(`the smoke path asked ${url}`);
      },
      log: () => {},
    });
    const { calls, fetchImpl } = answers([await worker.fetch(new Request(SMOKE_URL))]);
    const result = await smoke({ fetchImpl, ...quiet });
    assert.equal(result.ok, true);
    assert.deepEqual(calls, [SMOKE_URL]);
  });

  it("waits while the site's shell or no answer comes back, then passes", async () => {
    const { calls, fetchImpl } = answers([
      shell(),
      new TypeError("fetch failed"),
      fromWorker({ error: "not_found", detail: "x" }, 404),
    ]);
    const result = await smoke({ fetchImpl, ...quiet });
    assert.equal(result.ok, true);
    assert.equal(calls.length, 3);
  });

  it("fails when the answer never is the forwarder's 404", async () => {
    const unmarked = () => Response.json({ error: "not_found" }, { status: 404 });
    const { calls, fetchImpl } = answers([unmarked(), shell(), unmarked()]);
    const result = await smoke({ fetchImpl, attempts: 3, ...quiet });
    assert.equal(result.ok, false);
    assert.equal(calls.length, 3);
  });

  it("does not take the forwarder's other answers as its 404", () => {
    const json = "application/json; charset=utf-8";
    const base = { status: 404, marked: true, contentType: json, body: { error: "not_found" } };
    assert.equal(isForwarderNotFound(base), true);
    assert.equal(isForwarderNotFound({ ...base, marked: false }), false);
    assert.equal(isForwarderNotFound({ ...base, status: 200 }), false);
    assert.equal(isForwarderNotFound({ ...base, contentType: "text/html" }), false);
    assert.equal(isForwarderNotFound({ ...base, body: { error: "internal" } }), false);
  });
});

describe("the check after a delete", () => {
  it("passes once the smoke path answers without the Worker's marker", async () => {
    const { calls, fetchImpl } = answers([fromWorker({ error: "not_found" }, 404), shell()]);
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

  it("reads gone only from an HTTP answer without the marker", () => {
    assert.equal(showsGone({ status: 200, marked: false }), true);
    assert.equal(showsGone({ status: 404, marked: false }), true);
    assert.equal(showsGone({ status: 404, marked: true }), false);
    assert.equal(showsGone({ status: null, marked: false }), false);
    assert.equal(showsGone({ status: 429, marked: false }), false);
    assert.equal(showsGone({ status: 503, marked: false }), false);
  });
});

describe("the workflows", () => {
  const TEST_FILE = /workers\/fpl-proxy\/test\/[\w.-]+\.test\.mjs/g;
  const workflowText = (name) => text(new URL(name, WORKFLOWS));

  it("run every forwarder test file, in CI, before a deploy, and in the web guide's list", async () => {
    const onDisk = (await readdir(new URL("./", import.meta.url)))
      .filter((name) => name.endsWith(".test.mjs"))
      .map((name) => `workers/fpl-proxy/test/${name}`)
      .sort();
    for (const file of [
      new URL("ci.yml", WORKFLOWS),
      new URL("deploy-fpl-proxy.yml", WORKFLOWS),
      new URL("web/README.md", REPOSITORY),
    ]) {
      const named = [...new Set((await text(file)).match(TEST_FILE))].sort();
      assert.deepEqual(named, onDisk, file.pathname);
    }
  });

  it("is dispatched by hand only, from the default branch, into the Workers environment", async () => {
    const workflow = await workflowText("deploy-fpl-proxy.yml");
    const on = /^on:\n((?: {2}.*\n)+)/m.exec(workflow);
    assert.ok(on, "the workflow names its triggers");
    assert.deepEqual(
      [...on[1].matchAll(/^ {2}(\w+):/gm)].map((match) => match[1]),
      ["workflow_dispatch"],
    );
    assert.match(
      workflow,
      /if: github\.ref != format\('refs\/heads\/\{0\}', github\.event\.repository\.default_branch\)/,
    );
    assert.match(
      workflow,
      /if: github\.ref == format\('refs\/heads\/\{0\}', github\.event\.repository\.default_branch\)/,
    );
    assert.deepEqual(
      [...workflow.matchAll(/^\s*environment: (.+)$/gm)].map((match) => match[1]),
      ["cloudflare-workers"],
    );
    assert.deepEqual(
      [...new Set([...workflow.matchAll(/secrets\.([A-Z_]+)/g)].map((match) => match[1]))].sort(),
      ["CLOUDFLARE_ACCOUNT_ID", "CLOUDFLARE_WORKERS_API_TOKEN"],
    );
    const code = workflow.replace(/^\s*#.*$/gm, "");
    assert.doesNotMatch(code, /cloudflare-pages|CLOUDFLARE_API_TOKEN\b/);
  });

  it("uses the probe's pinned actions and wrangler version, and nothing else", async () => {
    const proxy = await workflowText("deploy-fpl-proxy.yml");
    const probe = await workflowText("deploy-fpl-probe.yml");
    const uses = (workflow) => new Set([...workflow.matchAll(/uses: (\S+)/g)].map((m) => m[1]));
    for (const action of uses(proxy)) {
      assert.match(action, /@[0-9a-f]{40}$/, action);
      assert.ok(uses(probe).has(action), `${action} is not the probe's pin`);
    }
    const versions = (workflow) =>
      new Set([...workflow.matchAll(/wranglerVersion: "([^"]+)"/g)].map((m) => m[1]));
    assert.deepEqual([...versions(proxy)], [...versions(probe)]);
    assert.equal(versions(proxy).size, 1);
  });

  it("delete the Worker before checking it is gone, deploy from its folder, then smoke", async () => {
    const workflow = await workflowText("deploy-fpl-proxy.yml");
    const step = (name) => {
      const at = workflow.indexOf(`- name: ${name}\n`);
      assert.notEqual(at, -1, name);
      return at;
    };
    assert.ok(
      step("Delete the forwarder Worker") < step("Confirm the forwarder no longer answers"),
    );
    assert.ok(step("Test the forwarder before it ships") < step("Deploy the forwarder Worker"));
    assert.ok(step("Deploy the forwarder Worker") < step("Smoke the forwarder"));
    assert.match(workflow, /command: delete --name squadopt-fpl-proxy --force\n/);
    assert.match(workflow, /workingDirectory: workers\/fpl-proxy\n\s+command: deploy\n/);
    assert.match(workflow, /run: node workers\/fpl-proxy\/scripts\/deploy-steps\.mjs smoke\n/);
    assert.match(
      workflow,
      /run: node workers\/fpl-proxy\/scripts\/deploy-steps\.mjs confirm-gone\n/,
    );
    const config = await text(new URL("../wrangler.toml", import.meta.url));
    assert.match(config, /^name = "squadopt-fpl-proxy"$/m);
  });
});
