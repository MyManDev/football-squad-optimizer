// Prints what the usage record holds for a date range: pages and tools opened, the steps of a
// visit, the member picker, languages, device classes and device-side solves.
//
//   CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_ANALYTICS_TOKEN=... \
//     node scripts/usage_report.mjs --from 2026-11-01 --to 2026-11-30 [--json]
//
// The dates are UTC days and both are included; --to defaults to today. The token needs the
// Account Analytics Read permission. Nothing is written anywhere and no session token is
// printed: sessions are only counted. See docs/architecture/decisions/0014-usage-measurement.md.

import { pathToFileURL } from "node:url";

import { BLOB_COLUMNS, DATASET } from "../workers/usage/src/rules.js";

/** The most rows one report reads; the report says so when the range holds more. */
export const ROW_LIMIT = 100_000;

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
 * `events` stays a count of what was sent if the dataset ever samples.
 */
export function reportQuery(from, to) {
  const columns = BLOB_COLUMNS.map((name, index) => `blob${index + 1} AS ${name}`).join(", ");
  return [
    `SELECT ${columns}, SUM(_sample_interval) AS events`,
    `FROM ${DATASET}`,
    `WHERE timestamp >= toDateTime('${from} 00:00:00') AND timestamp < toDateTime('${nextDay(to)} 00:00:00')`,
    `GROUP BY ${BLOB_COLUMNS.join(", ")}`,
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

/** The report, from the rows; a visit is one session token. */
export function summarize(rows) {
  const shown = sessionsAt(rows, "picker_shown");
  const claimed = [...sessionsAt(rows, "picker_claimed")].filter((session) => shown.has(session));
  const solves = rows.filter((row) => row.step === "device_solve");
  return {
    events: rows.reduce((sum, row) => sum + Number(row.events), 0),
    visits: new Set(rows.map((row) => row.session)).size,
    pages: tally(rows, "page", (row) => row.step === "open"),
    tools: tally(rows, "tool", (row) => row.step === "tool"),
    steps: tally(rows, "step"),
    languages: tally(rows, "lang"),
    devices: tally(rows, "device"),
    picker: { shown: shown.size, claimed: claimed.length, left: shown.size - claimed.length },
    device_solves: {
      events: solves.reduce((sum, row) => sum + Number(row.events), 0),
      visits: new Set(solves.map((row) => row.session)).size,
    },
  };
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
