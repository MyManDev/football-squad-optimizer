// Prints what the usage record holds for a date range: pages and tools opened, the steps of a
// visit, the member picker, languages, device classes and device-side solves (version 1 events,
// ADR 0014); and clicks by zone and cell, rage and dead clicks, scroll depth and time on page,
// speed, errors and arrivals (version 2 events, ADR 0015).
//
//   CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_ANALYTICS_TOKEN=... \
//     node scripts/usage_report.mjs --from 2026-11-01 --to 2026-11-30 [--json]
//
// The dates are UTC days and both are included; --to defaults to today. The token needs the
// Account Analytics Read permission. Nothing is written anywhere and no session token is
// printed: sessions are only counted. See docs/architecture/decisions/0014-usage-measurement.md
// and docs/architecture/decisions/0015-behaviour-measurement.md.
//
// --json prints one object, which the owner's dashboard reads. Its shape is stable: a field is
// only ever added, every list below is present (empty when nothing was sent), and every word
// map holds every word of its list, zero when nothing was sent. Counts are events with sampling
// undone; `visits` are distinct session tokens.
//
//   from, to                    the range, as given
//   truncated                   true when the row limit cut the range off; the counts are partial
//   events, visits              version 1 events, and the visits that sent them
//   pages, tools, steps,        [{ name, events, visits }], largest first; pages count `open`
//   languages, devices            steps and tools count `tool` steps, as before version 2
//   picker                      { shown, claimed, left } in visits
//   device_solves               { events, visits }
//   behaviour                   version 2 events:
//     events, visits
//     clicks                    [{ page, device, zone, cell, events,
//                                  marks: { none, rage, dead }, targets: { control, plain } }]
//                               by page, device, zone and cell; `cell` is row * 20 + column of
//                               the 20 by 20 grid over the zone
//     frustration               [{ page, zone, clicks, rage, dead }], most rage and dead first
//     scroll                    [{ page, device, events,
//                                  depth: { "0", "10", ..., "100" }, dwell: { s5, ..., long } }]
//                               page views by the deepest tenth seen and by time on the page
//     vitals                    [{ metric, page, device, events,
//                                  ratings: { good, needs, poor }, p75 }]
//                               ratings are shares of `events` (0 to 1, four decimals); `p75` is
//                               the 75th percentile of the value, in milliseconds or layout
//                               shift times 1000, weighted by the sample interval
//     errors                    [{ error, page, events, visits }], largest first
//     arrivals                  { sources: [{ name, events, visits }],
//                                 visits: [{ name, events, visits }] }, largest first

import { pathToFileURL } from "node:url";

import {
  BEHAVIOUR_VERSION,
  BLOB_COLUMNS,
  DATASET,
  DETAIL_COLUMNS,
  DWELLS,
  EVENT_VERSION,
  GRID,
  KIND_LAYOUT,
  MARKS,
  METRICS,
  NUMBER_RANGES,
  RATINGS,
  TARGETS,
} from "../workers/usage/src/rules.js";

/** The most rows one report reads; the report says so when the range holds more. */
export const ROW_LIMIT = 100_000;

/** The names the query gives `blob7` to `blob9`, and the two numbers. */
const DETAILS = Array.from({ length: DETAIL_COLUMNS }, (_, index) => `detail${index + 1}`);
const ALL_BLOBS = [...BLOB_COLUMNS, ...DETAILS];

const DAY = /^\d{4}-\d{2}-\d{2}$/;

function validDay(text) {
  if (!DAY.test(text)) return false;
  const parsed = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().startsWith(text);
}

function nextDay(text) {
  return new Date(Date.parse(`${text}T00:00:00Z`) + 86_400_000).toISOString().slice(0, 10);
}

/** The range the arguments name, or an error saying what is wrong with them. */
export function parseArguments(argv, today) {
  const options = { from: null, to: today, json: false };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument === "--json") options.json = true;
    else if (argument === "--from" || argument === "--to") {
      options[argument.slice(2)] = argv[index + 1] ?? "";
      index += 1;
    } else return { error: `unknown argument: ${argument}` };
  }
  if (options.from === null) return { error: "--from YYYY-MM-DD is required" };
  if (!validDay(options.from)) return { error: `--from is not a date: ${options.from}` };
  if (!validDay(options.to)) return { error: `--to is not a date: ${options.to}` };
  if (options.from > options.to) return { error: "--from is after --to" };
  return options;
}

/**
 * One row per distinct event shape in the range. Sampling is undone by `_sample_interval`, so
 * `events` stays a count of what was sent if the dataset ever samples. `blob3` is named `step`
 * here and holds a version 2 event's kind; a version 1 row has empty details and a zero
 * `measure`, which is what the dataset gives for a column a data point did not fill.
 */
export function reportQuery(from, to) {
  const columns = ALL_BLOBS.map((name, index) => `blob${index + 1} AS ${name}`).join(", ");
  return [
    `SELECT ${columns}, double1 AS v, double2 AS measure, SUM(_sample_interval) AS events`,
    `FROM ${DATASET}`,
    `WHERE timestamp >= toDateTime('${from} 00:00:00') AND timestamp < toDateTime('${nextDay(to)} 00:00:00')`,
    `GROUP BY ${[...ALL_BLOBS, "v", "measure"].join(", ")}`,
    `LIMIT ${ROW_LIMIT}`,
    "FORMAT JSON",
  ].join("\n");
}

/** Reads the rows of the query, and whether the row limit cut them off. */
export async function readRows({ accountId, token, query, fetchImpl = globalThis.fetch }) {
  const response = await fetchImpl(
    `https://api.cloudflare.com/client/v4/accounts/${accountId}/analytics_engine/sql`,
    { method: "POST", headers: { authorization: `Bearer ${token}` }, body: query },
  );
  const text = await response.text();
  if (!response.ok) throw new Error(`Analytics Engine answered ${response.status}: ${text.slice(0, 500)}`);
  const answer = JSON.parse(text);
  if (!Array.isArray(answer.data)) throw new Error("Analytics Engine's answer has no data rows");
  const before = Number(answer.rows_before_limit_at_least ?? answer.data.length);
  return { rows: answer.data, truncated: answer.data.length >= ROW_LIMIT || before > answer.data.length };
}

/** Events and distinct visits per value of `key`, among the rows `keep` accepts, largest first. */
function tally(rows, key, keep = () => true) {
  const groups = new Map();
  for (const row of rows) {
    if (!keep(row)) continue;
    const group = groups.get(row[key]) ?? { name: row[key], events: 0, sessions: new Set() };
    group.events += Number(row.events);
    group.sessions.add(row.session);
    groups.set(row[key], group);
  }
  return [...groups.values()]
    .map(({ name, events, sessions }) => ({ name, events, visits: sessions.size }))
    .sort((a, b) => b.events - a.events || a.name.localeCompare(b.name));
}

function sessionsAt(rows, step) {
  return new Set(rows.filter((row) => row.step === step).map((row) => row.session));
}

const sum = (rows) => rows.reduce((total, row) => total + Number(row.events), 0);

/** The version 1 tables, over version 1 rows only, exactly as before version 2 existed. */
function stepSummary(rows) {
  const shown = sessionsAt(rows, "picker_shown");
  const claimed = [...sessionsAt(rows, "picker_claimed")].filter((session) => shown.has(session));
  const solves = rows.filter((row) => row.step === "device_solve");
  return {
    events: sum(rows),
    visits: new Set(rows.map((row) => row.session)).size,
    pages: tally(rows, "page", (row) => row.step === "open"),
    tools: tally(rows, "tool", (row) => row.step === "tool"),
    steps: tally(rows, "step"),
    languages: tally(rows, "lang"),
    devices: tally(rows, "device"),
    picker: { shown: shown.size, claimed: claimed.length, left: shown.size - claimed.length },
    device_solves: {
      events: sum(solves),
      visits: new Set(solves.map((row) => row.session)).size,
    },
  };
}

/**
 * A version 2 row with its kind's fields named, or null for a kind this script does not know
 * (a row from a later version of the Worker is skipped rather than miscounted).
 */
function behaviourRow(row) {
  const layout = KIND_LAYOUT[row.step];
  if (layout === undefined) return null;
  const event = {
    page: row.page,
    tool: row.tool,
    kind: row.step,
    lang: row.lang,
    device: row.device,
    session: row.session,
    events: Number(row.events),
  };
  layout.words.forEach((field, index) => {
    event[field] = row[DETAILS[index]] ?? "";
  });
  if (layout.number !== null) event[layout.number] = Number(row.measure);
  return event;
}

/** A map holding every word of a list at zero. */
const zeros = (words) => Object.fromEntries([...words].map((word) => [word, 0]));

/** The depths a scroll can name: 0 to 100 in tenths. */
const DEPTHS = (() => {
  const { min, max, step } = NUMBER_RANGES.depth;
  const depths = [];
  for (let depth = min; depth <= max; depth += step) depths.push(String(depth));
  return depths;
})();

/**
 * One entry per distinct value of the fields `keys` names: the key fields, then what `start`
 * gives, with every event of the group handed to `add`.
 */
function grouped(events, keys, start, add) {
  const groups = new Map();
  for (const event of events) {
    const id = JSON.stringify(keys.map((key) => event[key]));
    if (!groups.has(id)) groups.set(id, { ...Object.fromEntries(keys.map((key) => [key, event[key]])), ...start() });
    add(groups.get(id), event);
  }
  return [...groups.values()];
}

const byKeys = (keys) => (a, b) => {
  for (const key of keys) {
    const order = typeof a[key] === "number" ? a[key] - b[key] : String(a[key]).localeCompare(String(b[key]));
    if (order !== 0) return order;
  }
  return 0;
};

/**
 * The value at or below which three quarters of the weight lies: the smallest value whose
 * running weight, in ascending order, reaches 75 per cent of the whole.
 */
export function weightedPercentile(pairs, share = 0.75) {
  const sorted = pairs.filter(([, weight]) => weight > 0).sort((a, b) => a[0] - b[0]);
  const total = sorted.reduce((whole, [, weight]) => whole + weight, 0);
  if (total === 0) return null;
  let running = 0;
  for (const [value, weight] of sorted) {
    running += weight;
    if (running >= share * total) return value;
  }
  return sorted[sorted.length - 1][0];
}

const shareOf = (part, whole) => (whole === 0 ? 0 : Math.round((part / whole) * 10_000) / 10_000);

/** The version 2 tables, over version 2 rows only. */
function behaviourSummary(rows) {
  const events = rows.map(behaviourRow).filter((event) => event !== null);
  const of = (kind) => events.filter((event) => event.kind === kind);
  const clicks = of("click");

  const cells = grouped(
    clicks,
    ["page", "device", "zone", "cell"],
    () => ({ events: 0, marks: zeros(MARKS), targets: zeros(TARGETS) }),
    (entry, click) => {
      entry.events += click.events;
      if (click.mark in entry.marks) entry.marks[click.mark] += click.events;
      if (click.target in entry.targets) entry.targets[click.target] += click.events;
    },
  ).sort(byKeys(["page", "device", "zone", "cell"]));

  const frustration = grouped(
    clicks,
    ["page", "zone"],
    () => ({ clicks: 0, rage: 0, dead: 0 }),
    (entry, click) => {
      entry.clicks += click.events;
      if (click.mark === "rage") entry.rage += click.events;
      if (click.mark === "dead") entry.dead += click.events;
    },
  ).sort((a, b) => b.rage + b.dead - (a.rage + a.dead) || byKeys(["page", "zone"])(a, b));

  const scroll = grouped(
    of("scroll"),
    ["page", "device"],
    () => ({ events: 0, depth: zeros(DEPTHS), dwell: zeros(DWELLS) }),
    (entry, view) => {
      entry.events += view.events;
      if (String(view.depth) in entry.depth) entry.depth[String(view.depth)] += view.events;
      if (view.dwell in entry.dwell) entry.dwell[view.dwell] += view.events;
    },
  ).sort(byKeys(["page", "device"]));

  const metricOrder = [...METRICS];
  const vitals = grouped(
    of("vital"),
    ["metric", "page", "device"],
    () => ({ events: 0, ratings: zeros(RATINGS), values: [] }),
    (entry, vital) => {
      entry.events += vital.events;
      if (vital.rating in entry.ratings) entry.ratings[vital.rating] += vital.events;
      entry.values.push([vital.value, vital.events]);
    },
  )
    .map(({ values, ...entry }) => ({
      ...entry,
      ratings: Object.fromEntries(Object.entries(entry.ratings).map(([rating, count]) => [rating, shareOf(count, entry.events)])),
      p75: weightedPercentile(values),
    }))
    .sort((a, b) => metricOrder.indexOf(a.metric) - metricOrder.indexOf(b.metric) || byKeys(["page", "device"])(a, b));

  const errors = grouped(
    of("error"),
    ["error", "page"],
    () => ({ events: 0, sessions: new Set() }),
    (entry, error) => {
      entry.events += error.events;
      entry.sessions.add(error.session);
    },
  )
    .map(({ sessions, ...entry }) => ({ ...entry, visits: sessions.size }))
    .sort((a, b) => b.events - a.events || byKeys(["error", "page"])(a, b));

  const arrivals = of("arrival");
  return {
    events: events.reduce((total, event) => total + event.events, 0),
    visits: new Set(events.map((event) => event.session)).size,
    clicks: cells,
    frustration,
    scroll,
    vitals,
    errors,
    arrivals: { sources: tally(arrivals, "source"), visits: tally(arrivals, "visit") },
  };
}

/** The report, from the rows; a visit is one session token. */
export function summarize(rows) {
  const steps = rows.filter((row) => Number(row.v) === EVENT_VERSION);
  const behaviour = rows.filter((row) => Number(row.v) === BEHAVIOUR_VERSION);
  return { ...stepSummary(steps), behaviour: behaviourSummary(behaviour) };
}

function table(title, entries) {
  const lines = [title];
  if (entries.length === 0) return [...lines, "  (none)"];
  const width = Math.max(...entries.map((entry) => (entry.name || "(no tool)").length));
  for (const { name, events, visits } of entries) {
    lines.push(`  ${(name || "(no tool)").padEnd(width)}  ${String(events).padStart(7)} events  ${String(visits).padStart(6)} visits`);
  }
  return lines;
}

/** Rows of text columns, padded to line up; `(none)` when there are no rows. */
function grid(title, rows) {
  if (rows.length === 0) return [title, "  (none)"];
  const widths = rows[0].map((_, column) => Math.max(...rows.map((row) => String(row[column]).length)));
  return [title, ...rows.map((row) => `  ${row.map((cell, column) => String(cell).padEnd(widths[column])).join("  ").trimEnd()}`)];
}

const percent = (share) => `${Math.round(share * 100)}%`;

/** A word map as `word count` pairs, leaving out the zeros. */
const counts = (map, suffix = "") =>
  Object.entries(map)
    .filter(([, count]) => count > 0)
    .map(([word, count]) => `${word}${suffix} ${count}`)
    .join(", ");

/** The click table in text: one line per page, device and zone, with its busiest cells. */
function clickLines(cells) {
  const zones = grouped(
    cells,
    ["page", "device", "zone"],
    () => ({ events: 0, rage: 0, dead: 0, cells: [] }),
    (entry, cell) => {
      entry.events += cell.events;
      entry.rage += cell.marks.rage;
      entry.dead += cell.marks.dead;
      entry.cells.push(cell);
    },
  );
  return zones.map((zone) => {
    const busiest = zone.cells
      .sort((a, b) => b.events - a.events || a.cell - b.cell)
      .slice(0, 5)
      .map(({ cell, events }) => `r${Math.floor(cell / GRID)}c${cell % GRID} ${events}`)
      .join(", ");
    return [zone.page, zone.device, zone.zone, `${zone.events} clicks`, `${zone.rage} rage`, `${zone.dead} dead`, `busiest: ${busiest}`];
  });
}

/** The version 2 sections as lines of text. */
function renderBehaviour(behaviour) {
  return [
    `Behaviour: ${behaviour.events} events in ${behaviour.visits} visits`,
    "",
    ...grid("Clicks by page, device and zone (cells as row and column of the 20 by 20 grid)", clickLines(behaviour.clicks)),
    "",
    ...grid(
      "Rage and dead clicks by page and zone",
      behaviour.frustration.map(({ page, zone, clicks, rage, dead }) => [page, zone, `${clicks} clicks`, `${rage} rage`, `${dead} dead`]),
    ),
    "",
    ...grid(
      "Scroll depth by page and device (page views by the deepest share seen)",
      behaviour.scroll.map(({ page, device, events, depth }) => [page, device, `${events} views`, counts(depth, "%")]),
    ),
    "",
    ...grid(
      "Time on page by page and device",
      behaviour.scroll.map(({ page, device, events, dwell }) => [page, device, `${events} views`, counts(dwell)]),
    ),
    "",
    ...grid(
      "Speed by metric, page and device (75th percentile; cls is layout shift times 1000)",
      behaviour.vitals.map(({ metric, page, device, events, ratings, p75 }) => [
        metric,
        page,
        device,
        `${events} readings`,
        `p75 ${p75}`,
        `good ${percent(ratings.good)}`,
        `needs ${percent(ratings.needs)}`,
        `poor ${percent(ratings.poor)}`,
      ]),
    ),
    "",
    ...grid(
      "Errors by kind and page",
      behaviour.errors.map(({ error, page, events, visits }) => [error, page, `${events} events`, `${visits} visits`]),
    ),
    "",
    ...table("Arrivals by source", behaviour.arrivals.sources),
    "",
    ...table("Arrivals by time since the last visit", behaviour.arrivals.visits),
  ];
}

/** The report as lines of text. */
export function render(report, { from, to, truncated }) {
  return [
    `Usage ${from} to ${to} (UTC days, inclusive)`,
    `${report.events} events in ${report.visits} visits`,
    ...(truncated ? [`WARNING: the range holds more than ${ROW_LIMIT} rows; these counts are partial.`] : []),
    "",
    ...table("Pages opened (the router reached the address)", report.pages),
    "",
    ...table("Tools opened (the page was drawn past its gates)", report.tools),
    "",
    ...table("Steps", report.steps),
    "",
    "Member picker",
    `  visits that reached it  ${report.picker.shown}`,
    `  visits that took a name ${report.picker.claimed}`,
    `  visits that left        ${report.picker.left}`,
    "",
    `Device-side solves started: ${report.device_solves.events} in ${report.device_solves.visits} visits`,
    "",
    ...table("Languages", report.languages),
    "",
    ...table("Device classes", report.devices),
    "",
    ...renderBehaviour(report.behaviour),
  ];
}

async function main(argv, env) {
  const options = parseArguments(argv, new Date().toISOString().slice(0, 10));
  if (options.error) {
    console.error(`${options.error}\nusage: node scripts/usage_report.mjs --from YYYY-MM-DD [--to YYYY-MM-DD] [--json]`);
    return 2;
  }
  const accountId = env.CLOUDFLARE_ACCOUNT_ID;
  const token = env.CLOUDFLARE_ANALYTICS_TOKEN;
  if (!accountId || !token) {
    console.error("CLOUDFLARE_ACCOUNT_ID and CLOUDFLARE_ANALYTICS_TOKEN (Account Analytics Read) must be set.");
    return 2;
  }
  try {
    const { rows, truncated } = await readRows({ accountId, token, query: reportQuery(options.from, options.to) });
    const report = summarize(rows);
    if (options.json) console.log(JSON.stringify({ from: options.from, to: options.to, truncated, ...report }, null, 2));
    else console.log(render(report, { from: options.from, to: options.to, truncated }).join("\n"));
    return 0;
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    return 1;
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  process.exitCode = await main(process.argv.slice(2), process.env);
}
