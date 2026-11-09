// The report script over rows handed to it: the query it sends, the counts it makes, and that
// no session token reaches its output.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ROW_LIMIT,
  parseArguments,
  readRows,
  render,
  reportQuery,
  summarize,
} from "../../../scripts/usage_report.mjs";
import { DATASET } from "../src/rules.js";

const A = "aaaaaaaaaaaaaaaa";
const B = "bbbbbbbbbbbbbbbb";
const C = "cccccccccccccccc";

const row = (session, step, page, tool, events = 1, lang = "tr", device = "phone") => ({
  page,
  tool,
  step,
  lang,
  device,
  session,
  // The SQL API may send a 64-bit sum as text.
  events: String(events),
});

const ROWS = [
  row(A, "open", "member", "week", 2),
  row(A, "picker_shown", "member", "week"),
  row(A, "picker_claimed", "member", "week"),
  row(A, "tool", "member", "what-if", 3),
  row(A, "device_solve", "member", "what-if", 2),
  row(B, "open", "league", "", 1, "en", "desktop"),
  row(B, "picker_shown", "league", "", 1, "en", "desktop"),
  row(C, "open", "fixtures", "fixtures", 1, "tr", "tablet"),
  row(C, "tool", "fixtures", "fixtures", 1, "tr", "tablet"),
];

describe("the arguments", () => {
  const today = "2026-11-09";

  it("take a range, with --to defaulting to today", () => {
    assert.deepEqual(parseArguments(["--from", "2026-11-01"], today), { from: "2026-11-01", to: today, json: false });
    assert.equal(parseArguments(["--from", "2026-11-01", "--to", "2026-11-02", "--json"], today).json, true);
  });

  it("refuse a missing, malformed, impossible or reversed date and an unknown flag", () => {
    assert.match(parseArguments([], today).error, /--from/);
    assert.match(parseArguments(["--from", "yesterday"], today).error, /not a date/);
    assert.match(parseArguments(["--from", "2026-02-31"], today).error, /not a date/);
    assert.match(parseArguments(["--from", "2026-11-05", "--to", "2026-11-01"], today).error, /after/);
    assert.match(parseArguments(["--from", "2026-11-01", "--bad"], today).error, /unknown/);
  });
});

describe("the query", () => {
  it("reads the columns in the Worker's order, undoes sampling, and includes the last day", () => {
    const query = reportQuery("2026-11-01", "2026-11-30");
    assert.match(query, /blob1 AS page, blob2 AS tool, blob3 AS step, blob4 AS lang, blob5 AS device, blob6 AS session/);
    assert.match(query, /SUM\(_sample_interval\) AS events/);
    assert.ok(query.includes(`FROM ${DATASET}`));
    assert.match(query, /timestamp >= toDateTime\('2026-11-01 00:00:00'\)/);
    assert.match(query, /timestamp < toDateTime\('2026-12-01 00:00:00'\)/);
    assert.match(query, /FORMAT JSON$/);
  });
});

describe("reading the rows", () => {
  const answer = (body, status = 200) => async () => new Response(JSON.stringify(body), { status });
  const read = (fetchImpl) => readRows({ accountId: "acc", token: "tok", query: "SELECT 1", fetchImpl });

  it("posts the SQL with the token to the account's address", async () => {
    let seen;
    const fetchImpl = async (url, init) => {
      seen = { url, init };
      return new Response(JSON.stringify({ data: [] }));
    };
    assert.deepEqual(await read(fetchImpl), { rows: [], truncated: false });
    assert.equal(seen.url, "https://api.cloudflare.com/client/v4/accounts/acc/analytics_engine/sql");
    assert.equal(seen.init.method, "POST");
    assert.equal(seen.init.headers.authorization, "Bearer tok");
    assert.equal(seen.init.body, "SELECT 1");
  });

  it("says when the limit cut the rows off", async () => {
    const { truncated } = await read(answer({ data: [{}], rows_before_limit_at_least: ROW_LIMIT + 5 }));
    assert.equal(truncated, true);
  });

  it("throws on a refused or shapeless answer", async () => {
    await assert.rejects(read(answer({ errors: ["no"] }, 403)), /answered 403/);
    await assert.rejects(read(answer({ meta: [] })), /no data rows/);
  });
});

describe("the summary", () => {
  const report = summarize(ROWS);
  const named = (list, name) => list.find((entry) => entry.name === name);

  it("counts events and distinct visits", () => {
    assert.equal(report.events, 13);
    assert.equal(report.visits, 3);
  });

  it("counts pages from the router's opens and tools from the pages drawn", () => {
    assert.deepEqual(named(report.pages, "member"), { name: "member", events: 2, visits: 1 });
    assert.equal(report.pages.length, 3);
    assert.deepEqual(named(report.tools, "what-if"), { name: "what-if", events: 3, visits: 1 });
    assert.deepEqual(report.tools.map((entry) => entry.name), ["what-if", "fixtures"]);
  });

  it("sets the visits that reached the picker against those that took a name", () => {
    assert.deepEqual(report.picker, { shown: 2, claimed: 1, left: 1 });
  });

  it("counts device solves, languages and device classes", () => {
    assert.deepEqual(report.device_solves, { events: 2, visits: 1 });
    assert.equal(named(report.languages, "en").visits, 1);
    assert.equal(named(report.devices, "tablet").visits, 1);
    assert.equal(named(report.devices, "phone").events, 9);
  });

  it("reads an empty range as zeros", () => {
    const empty = summarize([]);
    assert.equal(empty.events, 0);
    assert.deepEqual(empty.picker, { shown: 0, claimed: 0, left: 0 });
  });
});

describe("the printed report", () => {
  const text = (truncated = false) => render(summarize(ROWS), { from: "2026-11-01", to: "2026-11-30", truncated }).join("\n");

  it("prints every section and no session token", () => {
    const output = text();
    for (const heading of ["Pages opened", "Tools opened", "Steps", "Member picker", "Device-side solves", "Languages", "Device classes"]) {
      assert.ok(output.includes(heading), heading);
    }
    for (const session of [A, B, C]) assert.equal(output.includes(session), false);
  });

  it("warns when the counts are partial", () => {
    assert.equal(text().includes("WARNING"), false);
    assert.equal(text(true).includes("WARNING"), true);
  });
});
