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
// The query and every count live in workers/usage/src/report.js, which the usage Worker's
// report route (ADR 0016) uses too, so the admin page and this script cannot count differently.
// --json prints the object that module builds; its shape is described at the top of it. This
// script keeps the arguments, the read and the text.

import { pathToFileURL } from "node:url";

import {
  ROW_LIMIT,
  analyticsUrl,
  buildReport,
  grouped,
  reportQuery,
  rowsFromAnswer,
  validDay,
} from "../workers/usage/src/report.js";
import { GRID } from "../workers/usage/src/rules.js";

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

/** Reads the rows of the query, and whether the row limit cut them off. */
export async function readRows({ accountId, token, query, fetchImpl = globalThis.fetch }) {
  const response = await fetchImpl(analyticsUrl(accountId), {
    method: "POST",
    headers: { authorization: `Bearer ${token}` },
    body: query,
  });
  const text = await response.text();
  if (!response.ok) throw new Error(`Analytics Engine answered ${response.status}: ${text.slice(0, 500)}`);
  return rowsFromAnswer(JSON.parse(text));
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

/** A tool word as the text prints it: the empty word of a page with no tool is named. */
const toolName = (tool) => tool || "(no tool)";

/** The click table in text: one line per page, tool, device and zone, with its busiest cells. */
function clickLines(cells) {
  const zones = grouped(
    cells,
    ["page", "tool", "device", "zone"],
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
    return [zone.page, toolName(zone.tool), zone.device, zone.zone, `${zone.events} clicks`, `${zone.rage} rage`, `${zone.dead} dead`, `busiest: ${busiest}`];
  });
}

/** The version 2 sections as lines of text. */
function renderBehaviour(behaviour) {
  return [
    `Behaviour: ${behaviour.events} events in ${behaviour.visits} visits`,
    "",
    ...grid(
      "Clicks by page, tool, device and zone (cells as row and column of the 20 by 20 grid)",
      clickLines(behaviour.clicks),
    ),
    "",
    ...grid(
      "Rage and dead clicks by page, tool and zone",
      behaviour.frustration.map(({ page, tool, zone, clicks, rage, dead }) => [
        page,
        toolName(tool),
        zone,
        `${clicks} clicks`,
        `${rage} rage`,
        `${dead} dead`,
      ]),
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
    const report = buildReport({ from: options.from, to: options.to, truncated, rows });
    if (options.json) console.log(JSON.stringify(report, null, 2));
    else console.log(render(report, report).join("\n"));
    return 0;
  } catch (error) {
    console.error(error instanceof Error ? error.message : String(error));
    return 1;
  }
}

if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  process.exitCode = await main(process.argv.slice(2), process.env);
}
