// The deploy workflow's own steps, run with node --test. The workflow itself can only run
// against a Cloudflare account, so what it accepts as the Worker answering, and what the
// workflow and CI files say, are pinned here instead.

import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { describe, it } from "node:test";

import { SMOKE_URL, isStatusAnswer, smoke } from "../scripts/deploy-steps.mjs";
import { DATASET, MARKER_HEADER, MARKER_VALUE, STATUS_CONTRACT } from "../src/rules.js";
import { routeFor } from "../src/worker.js";

const REPOSITORY = new URL("../../../", import.meta.url);
const WORKFLOWS = new URL(".github/workflows/", REPOSITORY);
const quiet = { sleep: async () => {}, log: () => {} };
const GOOD = { contract_version: STATUS_CONTRACT, event_version: 1, bound: true };

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

const fromWorker = (body, status = 200) =>
  Response.json(body, { status, headers: { [MARKER_HEADER]: MARKER_VALUE } });

const shell = () =>
  new Response("<!doctype html><title>SquadOpt</title>", { headers: { "content-type": "text/html" } });

async function text(url) {
  return (await readFile(url, "utf8")).replace(/\r\n/g, "\n");
}

describe("the smoke after a deploy", () => {
  it("reads the status route, which is one of the Worker's own and writes nothing", () => {
    assert.equal(routeFor(new URL(SMOKE_URL).pathname), "status");
  });

  it("passes on a marked status with the dataset bound, and on nothing else", async () => {
    const good = answers([fromWorker(GOOD)]);
    const result = await smoke({ fetchImpl: good.fetchImpl, ...quiet });
    assert.equal(result.ok, true);
    assert.deepEqual(good.calls, [SMOKE_URL]);
    assert.equal(isStatusAnswer({ status: 200, marked: false, body: GOOD }), false);
    assert.equal(isStatusAnswer({ status: 200, marked: true, body: { ...GOOD, bound: false } }), false);
    assert.equal(isStatusAnswer({ status: 404, marked: true, body: { error: "no_such_route" } }), false);
  });

  it("retries while the site's shell answers in the Worker's place, then gives up", async () => {
    const late = answers([shell(), shell(), fromWorker(GOOD)]);
    assert.equal((await smoke({ fetchImpl: late.fetchImpl, attempts: 4, ...quiet })).ok, true);
    assert.equal(late.calls.length, 3);
    const never = answers([shell(), new Error("down"), shell()]);
    const result = await smoke({ fetchImpl: never.fetchImpl, attempts: 3, ...quiet });
    assert.equal(result.ok, false);
    assert.equal(result.attempts, 3);
  });
});

describe("the workflow and CI files", () => {
  const list = (yaml) => [...yaml.matchAll(/workers\/usage\/test\/([a-z-]+\.test\.mjs)/g)].map((m) => m[1]).sort();

  it("name every test file in this directory, in the deploy workflow and in ci.yml", async () => {
    const files = (await readdir(new URL(".", import.meta.url))).filter((f) => f.endsWith(".test.mjs")).sort();
    assert.deepEqual(list(await text(new URL("deploy-usage.yml", WORKFLOWS))), files);
    assert.deepEqual(list(await text(new URL("ci.yml", WORKFLOWS))), files);
  });

  it("dispatch only, from the default branch, and test before the deploy and smoke after it", async () => {
    const yaml = await text(new URL("deploy-usage.yml", WORKFLOWS));
    assert.match(yaml, /^on:\n  workflow_dispatch:/m);
    assert.doesNotMatch(yaml, /^\s+push:/m);
    assert.match(yaml, /reject non-default dispatch/);
    assert.match(yaml, /deploy-steps\.mjs smoke/);
    const order = ["Test the Worker", "Deploy the Worker", "Smoke the Worker"];
    const positions = order.map((step) => yaml.indexOf(`name: ${step}`));
    assert.ok(positions.every((p) => p >= 0), positions);
    assert.deepEqual([...positions].sort((a, b) => a - b), positions);
  });

  it("bind the dataset the report reads, on the site's route, with no request logs", async () => {
    const toml = await text(new URL("../wrangler.toml", import.meta.url));
    assert.match(toml, /binding = "USAGE_EVENTS"/);
    assert.ok(toml.includes(`dataset = "${DATASET}"`));
    assert.match(toml, /squadopt\.mymandev\.com\/api\/v1\/usage\/\*/);
    assert.match(toml, /invocation_logs = false/);
  });
});
