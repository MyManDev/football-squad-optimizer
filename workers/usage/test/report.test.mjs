// The report script over rows handed to it: the query it sends, the counts it makes, and that
// no session token reaches its output. Version 1 rows and version 2 rows are counted apart.

import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  ROW_LIMIT,
  parseArguments,
  readRows,
  render,
  reportQuery,
  summarize,
  weightedPercentile,
} from "../../../scripts/usage_report.mjs";
import { DATASET, DWELLS } from "../src/rules.js";

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
  // A version 1 data point fills none of these; the dataset reads them as empty and zero.
  detail1: "",
  detail2: "",
  detail3: "",
  v: 1,
  measure: 0,
  // The SQL API may send a 64-bit sum as text.
  events: String(events),
});

/** A version 2 row: the kind in `step`, its words in the details and its number in `measure`. */
const behaviour = (session, kind, words, measure, { events = 1, page = "member", device = "phone" } = {}) => ({
  page,
  tool: page === "member" ? "week" : "",
  step: kind,
  lang: "tr",
  device,
  session,
  detail1: words[0] ?? "",
  detail2: words[1] ?? "",
  detail3: words[2] ?? "",
  v: 2,
  measure,
  events: String(events),
});

const desktop = { device: "desktop" };
const BEHAVIOUR_ROWS = [
  behaviour(A, "click", ["decision", "control", "none"], 47, { events: 5 }),
  behaviour(A, "click", ["decision", "control", "rage"], 47),
  behaviour(B, "click", ["decision", "plain", "dead"], 48, { events: 2 }),
  behaviour(C, "click", ["page", "plain", "none"], 0, { events: 3, ...desktop }),
  behaviour(A, "click", ["nav", "control", "none"], 3, { page: "league" }),
  behaviour(A, "scroll", ["s30"], 60, { events: 2 }),
  behaviour(B, "scroll", ["s5"], 10),
  behaviour(C, "scroll", ["long"], 100, { page: "league", ...desktop }),
  behaviour(A, "vital", ["lcp", "good"], 1000, { events: 3 }),
  behaviour(B, "vital", ["lcp", "good"], 2000, { events: 3 }),
  behaviour(C, "vital", ["lcp", "needs"], 3000),
  behaviour(A, "vital", ["lcp", "poor"], 5000),
  behaviour(A, "vital", ["cls", "good"], 120),
  behaviour(A, "error", ["chunk"], 0),
  behaviour(B, "error", ["chunk"], 0),
  behaviour(A, "error", ["script"], 0, { events: 3, page: "league" }),
  behaviour(A, "arrival", ["whatsapp", "new"], 0),
  behaviour(B, "arrival", ["google", "last_week"], 0),
  behaviour(C, "arrival", ["whatsapp", "same_week"], 0),
  // Neither of these is a row this script knows; both are left out of every count.
  { ...behaviour(A, "click", ["nav", "control", "none"], 3), v: 3 },
  behaviour(A, "pageview", [], 0, { events: 50 }),
];

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
    assert.match(query, /blob7 AS detail1, blob8 AS detail2, blob9 AS detail3, double1 AS v, double2 AS measure/);
    assert.match(query, /SUM\(_sample_interval\) AS events/);
    assert.match(query, /GROUP BY page, tool, step, lang, device, session, detail1, detail2, detail3, v, measure/);
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

describe("version 1's tables beside version 2 rows", () => {
  it("hold the same numbers as over version 1 rows alone", () => {
    const alone = summarize(ROWS);
    const mixed = summarize([...ROWS, ...BEHAVIOUR_ROWS]);
    const { behaviour: _alone, ...stepsAlone } = alone;
    const { behaviour: _mixed, ...stepsMixed } = mixed;
    assert.deepEqual(stepsMixed, stepsAlone);
    assert.equal(mixed.events, 13);
  });
});

describe("the behaviour summary", () => {
  const { behaviour: report } = summarize([...ROWS, ...BEHAVIOUR_ROWS]);

  it("counts version 2 events and their visits, leaving out rows it does not know", () => {
    assert.equal(report.events, 33);
    assert.equal(report.visits, 3);
  });

  it("counts clicks by page, device, zone and cell, with their marks and targets", () => {
    assert.deepEqual(report.clicks, [
      { page: "league", device: "phone", zone: "nav", cell: 3, events: 1, marks: { none: 1, rage: 0, dead: 0 }, targets: { control: 1, plain: 0 } },
      { page: "member", device: "desktop", zone: "page", cell: 0, events: 3, marks: { none: 3, rage: 0, dead: 0 }, targets: { control: 0, plain: 3 } },
      { page: "member", device: "phone", zone: "decision", cell: 47, events: 6, marks: { none: 5, rage: 1, dead: 0 }, targets: { control: 6, plain: 0 } },
      { page: "member", device: "phone", zone: "decision", cell: 48, events: 2, marks: { none: 0, rage: 0, dead: 2 }, targets: { control: 0, plain: 2 } },
    ]);
  });

  it("counts rage and dead clicks by page and zone, most first", () => {
    assert.deepEqual(report.frustration, [
      { page: "member", zone: "decision", clicks: 8, rage: 1, dead: 2 },
      { page: "league", zone: "nav", clicks: 1, rage: 0, dead: 0 },
      { page: "member", zone: "page", clicks: 3, rage: 0, dead: 0 },
    ]);
  });

  it("spreads page views over every depth and every dwell, by page and device", () => {
    const [league, member] = report.scroll;
    assert.deepEqual([league.page, league.device, member.page, member.device], ["league", "desktop", "member", "phone"]);
    assert.deepEqual(Object.keys(member.depth), ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"]);
    assert.deepEqual(Object.keys(member.dwell), [...DWELLS]);
    assert.equal(member.events, 3);
    assert.equal(member.depth["60"], 2);
    assert.equal(member.depth["10"], 1);
    assert.equal(member.depth["100"], 0);
    assert.deepEqual(member.dwell, { s5: 1, s15: 0, s30: 2, s60: 0, s180: 0, s600: 0, long: 0 });
    assert.equal(league.depth["100"], 1);
    assert.equal(league.dwell.long, 1);
  });

  it("gives each vital's rating shares and its 75th percentile weighted by the sample interval", () => {
    assert.deepEqual(report.vitals, [
      { metric: "lcp", page: "member", device: "phone", events: 8, ratings: { good: 0.75, needs: 0.125, poor: 0.125 }, p75: 2000 },
      { metric: "cls", page: "member", device: "phone", events: 1, ratings: { good: 1, needs: 0, poor: 0 }, p75: 120 },
    ]);
  });

  it("counts errors by kind and page, and the visits that met them", () => {
    assert.deepEqual(report.errors, [
      { error: "script", page: "league", events: 3, visits: 1 },
      { error: "chunk", page: "member", events: 2, visits: 2 },
    ]);
  });

  it("counts arrivals by source and by time since the last visit", () => {
    assert.deepEqual(report.arrivals.sources, [
      { name: "whatsapp", events: 2, visits: 2 },
      { name: "google", events: 1, visits: 1 },
    ]);
    assert.deepEqual(report.arrivals.visits.map((entry) => entry.name), ["last_week", "new", "same_week"]);
  });

  it("keeps its shape when nothing was sent", () => {
    const empty = summarize(ROWS).behaviour;
    assert.deepEqual(empty, {
      events: 0,
      visits: 0,
      clicks: [],
      frustration: [],
      scroll: [],
      vitals: [],
      errors: [],
      arrivals: { sources: [], visits: [] },
    });
  });

  it("prints as JSON with no session token in it", () => {
    const json = JSON.stringify(summarize([...ROWS, ...BEHAVIOUR_ROWS]));
    for (const session of [A, B, C]) assert.equal(json.includes(session), false);
    assert.deepEqual(Object.keys(JSON.parse(json)), [
      "events", "visits", "pages", "tools", "steps", "languages", "devices", "picker", "device_solves", "behaviour",
    ]);
  });
});

describe("the weighted percentile", () => {
  it("is the smallest value whose running weight reaches the share", () => {
    assert.equal(weightedPercentile([[3000, 1], [1000, 3], [5000, 1], [2000, 3]]), 2000);
    assert.equal(weightedPercentile([[10, 1], [20, 1], [30, 1], [40, 1]]), 30);
    assert.equal(weightedPercentile([[7, 1]]), 7);
    assert.equal(weightedPercentile([[10, 1], [20, 1]], 0.5), 10);
  });

  it("is nothing when there is no weight", () => {
    assert.equal(weightedPercentile([]), null);
    assert.equal(weightedPercentile([[10, 0]]), null);
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

  it("prints the behaviour sections after version 1's, and no session token", () => {
    const output = render(summarize([...ROWS, ...BEHAVIOUR_ROWS]), { from: "2026-11-01", to: "2026-11-30", truncated: false }).join("\n");
    const headings = [
      "Behaviour: 33 events in 3 visits",
      "Clicks by page, device and zone",
      "Rage and dead clicks",
      "Scroll depth",
      "Time on page",
      "Speed by metric",
      "Errors by kind and page",
      "Arrivals by source",
      "Arrivals by time since the last visit",
    ];
    for (const heading of headings) assert.ok(output.includes(heading), heading);
    assert.ok(output.indexOf("Device classes") < output.indexOf("Behaviour:"));
    assert.match(output, /decision\s+8 clicks\s+1 rage\s+2 dead/);
    assert.match(output, /lcp\s+member\s+phone\s+8 readings\s+p75 2000\s+good 75%/);
    assert.match(output, /busiest: r2c7 6, r2c8 2/);
    for (const session of [A, B, C]) assert.equal(output.includes(session), false);
  });

  it("says (none) under each behaviour section when nothing was sent", () => {
    const output = text();
    assert.ok(output.includes("Behaviour: 0 events in 0 visits"));
    assert.ok(output.split("\n").filter((line) => line === "  (none)").length >= 8);
  });

  it("warns when the counts are partial", () => {
    assert.equal(text().includes("WARNING"), false);
    assert.equal(text(true).includes("WARNING"), true);
  });
});
