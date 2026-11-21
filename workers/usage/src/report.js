// The usage report's query and arithmetic, as plain functions with no I/O: the SQL that reads a
// date range from Analytics Engine, and the counts made from the rows it answers. The Worker's
// report route (ADR 0016) and scripts/usage_report.mjs both use this one module, so the page and
// the script cannot count differently. Neither prints or returns a session token: sessions are
// only counted.
//
// The report's shape is stable: a field is only ever added, every list below is present (empty
// when nothing was sent), and every word map holds every word of its list, zero when nothing was
// sent. Counts are events with sampling undone; `visits` are distinct session tokens.
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
//
// See docs/architecture/decisions/0014-usage-measurement.md, 0015-behaviour-measurement.md and
// 0016-usage-admin-views.md.

import {
  BEHAVIOUR_VERSION,
  BLOB_COLUMNS,
  DATASET,
  DETAIL_COLUMNS,
  DWELLS,
  EVENT_VERSION,
  KIND_LAYOUT,
  MARKS,
  METRICS,
  NUMBER_RANGES,
  RATINGS,
  TARGETS,
} from "./rules.js";

/** The most rows one report reads; the report says so when the range holds more. */
export const ROW_LIMIT = 100_000;

/** What the admin check answers, for a signed-in person the Access policy names. */
export const ADMIN_CONTRACT = "usage_admin_v1";

/** The longest range the Worker's report route reads, in UTC days, both ends included. */
export const MAX_RANGE_DAYS = 92;

/** The names the query gives `blob7` to `blob9`, and the two numbers. */
const DETAILS = Array.from({ length: DETAIL_COLUMNS }, (_, index) => `detail${index + 1}`);
const ALL_BLOBS = [...BLOB_COLUMNS, ...DETAILS];

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 86_400_000;

/** A real calendar day written as YYYY-MM-DD; 2026-02-31 is not one. */
export function validDay(text) {
  if (typeof text !== "string" || !DAY.test(text)) return false;
  const parsed = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().startsWith(text);
}

function nextDay(text) {
  return new Date(Date.parse(`${text}T00:00:00Z`) + DAY_MS).toISOString().slice(0, 10);
}

/**
 * Why the Worker refuses to read a range, as a word, or null when it may: both ends real days,
 * in order, at most MAX_RANGE_DAYS long and ending no later than `today` (a UTC day). The script
 * is the owner's own tool and keeps its looser rules; this bound is for the public address.
 */
export function rangeRefusal(from, to, today) {
  if (!validDay(from)) return "from_not_a_date";
  if (!validDay(to)) return "to_not_a_date";
  if (from > to) return "from_after_to";
  if (to > today) return "to_in_future";
  const days = (Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS + 1;
  if (days > MAX_RANGE_DAYS) return "range_too_long";
  return null;
}

/** Where the account's Analytics Engine SQL API takes a query. */
export function analyticsUrl(accountId) {
  return `https://api.cloudflare.com/client/v4/accounts/${accountId}/analytics_engine/sql`;
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

/** The rows of the SQL API's parsed answer, and whether the row limit cut them off. */
export function rowsFromAnswer(answer) {
  if (answer === null || typeof answer !== "object" || !Array.isArray(answer.data)) {
    throw new Error("Analytics Engine's answer has no data rows");
  }
  // Only a full page of rows says the limit cut the range off. The SQL API's
  // `rows_before_limit_at_least` counts the rows it read before grouping, not the groups, so
  // it is above the answer's length on every grouped query and said nothing here.
  return { rows: answer.data, truncated: answer.data.length >= ROW_LIMIT };
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
 * A version 2 row with its kind's fields named, or null for a kind this module does not know
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
 * gives, with every event of the group handed to `add`. The script's text output groups with it
 * too.
 */
export function grouped(events, keys, start, add) {
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

/** The counts, from the rows; a visit is one session token. */
export function summarize(rows) {
  const steps = rows.filter((row) => Number(row.v) === EVENT_VERSION);
  const behaviour = rows.filter((row) => Number(row.v) === BEHAVIOUR_VERSION);
  return { ...stepSummary(steps), behaviour: behaviourSummary(behaviour) };
}

/** The whole report as `--json` prints it and the Worker answers it. */
export function buildReport({ from, to, truncated, rows }) {
  return { from, to, truncated, ...summarize(rows) };
}
