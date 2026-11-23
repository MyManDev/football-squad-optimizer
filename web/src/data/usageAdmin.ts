/**
 * The usage record read back (ADR 0016): the report for a range of UTC days, and whether the
 * person asking may read it. Both routes sit behind Cloudflare Access on the site's own host,
 * so the request is same-origin with its cookies, and a redirect is not followed: Access
 * answers a person who is not signed in with one, which the browser hands back as an opaque
 * redirect and this module reads as `signed_out`.
 *
 * Every answer is one of five states, and the report's shape is checked before a page sees
 * it: a field of the wrong kind makes the whole answer `failed`, never a half-drawn page.
 * Nothing here throws.
 */
import { withRequestDeadline } from "./request";
import { USAGE_DWELLS } from "./usageBehaviour";

export type UsageAdminFailure = "signed_out" | "refused" | "not_configured" | "failed";

export type UsageAdminAnswer<T> = { state: "ok"; value: T } | { state: UsageAdminFailure };

/** A range of UTC days, both included, as `YYYY-MM-DD`. */
export interface UsageRange {
  from: string;
  to: string;
}

export interface UsageTally {
  name: string;
  events: number;
  visits: number;
}

/**
 * The tool a click row names: the event's `tool` word, "" on a page with no tool, or null when
 * the answer did not say (a Worker from before 2026-11-23, whose rows merged a page's tools).
 */
export type UsageRowTool = string | null;

export interface UsageClickCell {
  page: string;
  tool: UsageRowTool;
  device: string;
  zone: string;
  cell: number;
  events: number;
  marks: { none: number; rage: number; dead: number };
  targets: { control: number; plain: number };
}

export interface UsageFrustration {
  page: string;
  tool: UsageRowTool;
  zone: string;
  clicks: number;
  rage: number;
  dead: number;
}

export interface UsageScroll {
  page: string;
  device: string;
  events: number;
  /** Page views by the deepest tenth seen, "0" to "100". */
  depth: Record<string, number>;
  /** Page views by time on the page, `s5` to `long`. */
  dwell: Record<string, number>;
}

export interface UsageVital {
  metric: string;
  page: string;
  device: string;
  events: number;
  /** Shares of `events`, 0 to 1. */
  ratings: { good: number; needs: number; poor: number };
  /** Milliseconds, or layout shift times 1000; null when nothing was measured. */
  p75: number | null;
}

export interface UsageError {
  error: string;
  page: string;
  events: number;
  visits: number;
}

export interface UsageReport {
  from: string;
  to: string;
  truncated: boolean;
  events: number;
  visits: number;
  pages: UsageTally[];
  tools: UsageTally[];
  steps: UsageTally[];
  languages: UsageTally[];
  devices: UsageTally[];
  picker: { shown: number; claimed: number; left: number };
  device_solves: { events: number; visits: number };
  behaviour: {
    events: number;
    visits: number;
    clicks: UsageClickCell[];
    frustration: UsageFrustration[];
    scroll: UsageScroll[];
    vitals: UsageVital[];
    errors: UsageError[];
    arrivals: { sources: UsageTally[]; visits: UsageTally[] };
  };
}

/** The depths a scroll names, 0 to 100 in tenths, as `workers/usage/src/rules.js` lists them. */
export const USAGE_DEPTHS = ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"];

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MS = 86_400_000;

/** Whether a text is a real calendar day as `YYYY-MM-DD`. */
export function isUtcDay(text: string): boolean {
  if (!DAY.test(text)) return false;
  const parsed = new Date(`${text}T00:00:00Z`);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().startsWith(text);
}

/** The UTC day a moment falls on. */
export function utcDay(moment: Date): string {
  return moment.toISOString().slice(0, 10);
}

/** The range of `days` UTC days ending with the one `now` falls on. */
export function rangeEnding(days: number, now: Date = new Date()): UsageRange {
  const to = utcDay(now);
  const from = utcDay(new Date(Date.parse(`${to}T00:00:00Z`) - (days - 1) * DAY_MS));
  return { from, to };
}

/** The number of UTC days a range holds, both ends included. */
export function rangeDays({ from, to }: UsageRange): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / DAY_MS) + 1;
}

/** The most days one report reads, as the Worker holds it. */
export const MAX_RANGE_DAYS = 92;

/** Whether the Worker takes a range: real days, in order, at most 92, ending by today. */
export function rangeIsReadable(range: UsageRange, now: Date = new Date()): boolean {
  return (
    isUtcDay(range.from) &&
    isUtcDay(range.to) &&
    range.from <= range.to &&
    range.to <= utcDay(now) &&
    rangeDays(range) <= MAX_RANGE_DAYS
  );
}

// ---- The shape, checked ----

type Shape = Record<string, unknown>;

const isObject = (value: unknown): value is Shape =>
  typeof value === "object" && value !== null && !Array.isArray(value);

const isCount = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0;

const isShare = (value: unknown): value is number => isCount(value) && value <= 1;

const isText = (value: unknown): value is string => typeof value === "string";

/** Thrown inside the checks; `parseUsageReport` turns any failure into null. */
class ShapeError extends Error {}

function need<T>(value: unknown, test: (value: unknown) => value is T): T {
  if (!test(value)) throw new ShapeError();
  return value;
}

function list<T>(value: unknown, item: (entry: Shape) => T): T[] {
  if (!Array.isArray(value)) throw new ShapeError();
  return value.map((entry) => item(need(entry, isObject)));
}

/** A word map: every listed word's count, zero when the answer left it out. */
function counts(value: unknown, words: readonly string[]): Record<string, number> {
  const map = need(value, isObject);
  const out: Record<string, number> = {};
  for (const word of words) out[word] = map[word] === undefined ? 0 : need(map[word], isCount);
  return out;
}

/** A row's tool: its word, or null when an older answer left the field out. */
const toolOf = (entry: Shape): UsageRowTool =>
  entry.tool === undefined ? null : need(entry.tool, isText);

const tally = (entry: Shape): UsageTally => ({
  name: need(entry.name, isText),
  events: need(entry.events, isCount),
  visits: need(entry.visits, isCount),
});

function behaviourOf(value: unknown): UsageReport["behaviour"] {
  const behaviour = need(value, isObject);
  const arrivals = need(behaviour.arrivals, isObject);
  return {
    events: need(behaviour.events, isCount),
    visits: need(behaviour.visits, isCount),
    clicks: list(behaviour.clicks, (entry) => {
      const marks = counts(entry.marks, ["none", "rage", "dead"]);
      const targets = counts(entry.targets, ["control", "plain"]);
      const cell = need(entry.cell, isCount);
      if (!Number.isInteger(cell) || cell >= 400) throw new ShapeError();
      return {
        page: need(entry.page, isText),
        tool: toolOf(entry),
        device: need(entry.device, isText),
        zone: need(entry.zone, isText),
        cell,
        events: need(entry.events, isCount),
        marks: { none: marks.none!, rage: marks.rage!, dead: marks.dead! },
        targets: { control: targets.control!, plain: targets.plain! },
      };
    }),
    frustration: list(behaviour.frustration, (entry) => ({
      page: need(entry.page, isText),
      tool: toolOf(entry),
      zone: need(entry.zone, isText),
      clicks: need(entry.clicks, isCount),
      rage: need(entry.rage, isCount),
      dead: need(entry.dead, isCount),
    })),
    scroll: list(behaviour.scroll, (entry) => ({
      page: need(entry.page, isText),
      device: need(entry.device, isText),
      events: need(entry.events, isCount),
      depth: counts(entry.depth, USAGE_DEPTHS),
      dwell: counts(entry.dwell, USAGE_DWELLS),
    })),
    vitals: list(behaviour.vitals, (entry) => {
      const ratings = need(entry.ratings, isObject);
      return {
        metric: need(entry.metric, isText),
        page: need(entry.page, isText),
        device: need(entry.device, isText),
        events: need(entry.events, isCount),
        ratings: {
          good: need(ratings.good ?? 0, isShare),
          needs: need(ratings.needs ?? 0, isShare),
          poor: need(ratings.poor ?? 0, isShare),
        },
        p75: entry.p75 === null ? null : need(entry.p75, isCount),
      };
    }),
    errors: list(behaviour.errors, (entry) => ({
      error: need(entry.error, isText),
      page: need(entry.page, isText),
      events: need(entry.events, isCount),
      visits: need(entry.visits, isCount),
    })),
    arrivals: { sources: list(arrivals.sources, tally), visits: list(arrivals.visits, tally) },
  };
}

/** The report, when the answer has its shape; null otherwise. */
export function parseUsageReport(value: unknown): UsageReport | null {
  try {
    const report = need(value, isObject);
    const picker = need(report.picker, isObject);
    const solves = need(report.device_solves, isObject);
    return {
      from: need(report.from, isText),
      to: need(report.to, isText),
      truncated: report.truncated === true,
      events: need(report.events, isCount),
      visits: need(report.visits, isCount),
      pages: list(report.pages, tally),
      tools: list(report.tools, tally),
      steps: list(report.steps, tally),
      languages: list(report.languages, tally),
      devices: list(report.devices, tally),
      picker: {
        shown: need(picker.shown, isCount),
        claimed: need(picker.claimed, isCount),
        left: need(picker.left, isCount),
      },
      device_solves: { events: need(solves.events, isCount), visits: need(solves.visits, isCount) },
      behaviour: behaviourOf(report.behaviour),
    };
  } catch {
    return null;
  }
}

// ---- The requests ----

const REPORT_PATH = "/api/v1/usage/report";
/** The version `/report/me` names; another answer is not one this site reads. */
export const ADMIN_CONTRACT = "usage_admin_v1";

/**
 * One same-origin GET, read as JSON. Access's redirect is not followed; a 401 is read as the
 * sign-in having lapsed too, as Access answers some requests that way.
 */
async function readJson(path: string): Promise<UsageAdminAnswer<unknown>> {
  try {
    return await withRequestDeadline(async (signal) => {
      const response = await fetch(path, {
        method: "GET",
        credentials: "same-origin",
        redirect: "manual",
        cache: "no-store",
        headers: { accept: "application/json" },
        signal,
      });
      if (response.type === "opaqueredirect" || response.status === 401) {
        return { state: "signed_out" };
      }
      if (response.status === 403) return { state: "refused" };
      if (response.status === 503) return { state: "not_configured" };
      if (!response.ok) return { state: "failed" };
      const text = await response.text();
      try {
        return { state: "ok", value: JSON.parse(text) as unknown };
      } catch {
        return { state: "failed" };
      }
    });
  } catch {
    return { state: "failed" };
  }
}

/** The report for a range of UTC days. */
export async function readUsageReport(range: UsageRange): Promise<UsageAdminAnswer<UsageReport>> {
  const query = new URLSearchParams({ from: range.from, to: range.to });
  const answer = await readJson(`${REPORT_PATH}?${query.toString()}`);
  if (answer.state !== "ok") return answer;
  const report = parseUsageReport(answer.value);
  return report === null ? { state: "failed" } : { state: "ok", value: report };
}

/** Whether the person asking may read the report; reads nothing of the record. */
export async function readUsageAdminMe(): Promise<UsageAdminAnswer<true>> {
  const answer = await readJson(`${REPORT_PATH}/me`);
  if (answer.state !== "ok") return answer;
  const body = answer.value;
  return isObject(body) && body.contract_version === ADMIN_CONTRACT && body.admin === true
    ? { state: "ok", value: true }
    : { state: "failed" };
}
