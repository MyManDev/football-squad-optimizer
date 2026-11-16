/**
 * The figures the admin page draws from a usage report (ADR 0016): the totals' shares, the
 * funnel, scroll depth read as "at least this far", the speed ratings and the clicks of one
 * page and device by zone. Pure arithmetic over the report's shape, so each is tested alone.
 */
import {
  USAGE_DEPTHS,
  type UsageReport,
  type UsageScroll,
  type UsageTally,
} from "../../data/usageAdmin";

/** A part of a whole, 0 to 1; null when the whole is nothing. */
export function shareOf(part: number, whole: number): number | null {
  return whole > 0 ? part / whole : null;
}

const visitsOf = (entries: readonly UsageTally[], name: string): number =>
  entries.find((entry) => entry.name === name)?.visits ?? 0;

/** The visit buckets that came back: everything known but a first visit. */
export const RETURNING_VISITS = ["same_week", "last_week", "weeks_2_4", "older"] as const;

export interface UsageTotals {
  visits: number;
  /** Every event of both versions. */
  events: number;
  /** Visits that took a name, of those shown the picker. */
  claimShare: number | null;
  /** Arriving visits that had been before, of those whose last visit is known. */
  returningShare: number | null;
  /** Visits from a phone, of the visits each device class counted. */
  phoneShare: number | null;
  /** Rage and dead clicks, of all clicks. */
  frustrationShare: number | null;
}

export function usageTotals(report: UsageReport): UsageTotals {
  const arrivals = report.behaviour.arrivals.visits;
  const returning = RETURNING_VISITS.reduce((sum, name) => sum + visitsOf(arrivals, name), 0);
  const known = returning + visitsOf(arrivals, "new");
  const deviceVisits = report.devices.reduce((sum, entry) => sum + entry.visits, 0);
  const clicks = report.behaviour.frustration.reduce(
    (sum, entry) => ({ all: sum.all + entry.clicks, marked: sum.marked + entry.rage + entry.dead }),
    { all: 0, marked: 0 },
  );
  return {
    visits: report.visits,
    events: report.events + report.behaviour.events,
    claimShare: shareOf(report.picker.claimed, report.picker.shown),
    returningShare: shareOf(returning, known),
    phoneShare: shareOf(visitsOf(report.devices, "phone"), deviceVisits),
    frustrationShare: shareOf(clicks.marked, clicks.all),
  };
}

/** Whether the range holds nothing at all. */
export function reportIsEmpty(report: UsageReport): boolean {
  return report.events === 0 && report.behaviour.events === 0;
}

/** A visit's steps in the order a visit takes them. */
export const FUNNEL_STEPS = [
  "open",
  "picker_shown",
  "picker_claimed",
  "tool",
  "device_solve",
] as const;
export type FunnelStep = (typeof FUNNEL_STEPS)[number];

export interface FunnelRow {
  step: FunnelStep;
  visits: number;
  /** Of the visits that opened a page. */
  share: number | null;
}

export function funnel(report: UsageReport): FunnelRow[] {
  const opened = visitsOf(report.steps, "open");
  return FUNNEL_STEPS.map((step) => {
    const visits = visitsOf(report.steps, step);
    return { step, visits, share: shareOf(visits, opened) };
  });
}

export interface DepthRow {
  /** The tenth of the page, 10 to 100. */
  depth: number;
  /** Page views that saw at least this far. */
  views: number;
  share: number | null;
}

/**
 * Page views that saw at least each tenth of the page: the depth buckets hold the deepest
 * tenth each view reached, so "at least X" is the sum of every bucket from X up. Zero is left
 * out, since every view saw at least that much.
 */
export function cumulativeDepth(depth: UsageScroll["depth"]): DepthRow[] {
  const total = USAGE_DEPTHS.reduce((sum, bucket) => sum + (depth[bucket] ?? 0), 0);
  const rows: DepthRow[] = [];
  let atLeast = 0;
  for (const bucket of [...USAGE_DEPTHS].reverse()) {
    atLeast += depth[bucket] ?? 0;
    if (bucket !== "0")
      rows.push({ depth: Number(bucket), views: atLeast, share: shareOf(atLeast, total) });
  }
  return rows.reverse();
}

export type VitalRating = "good" | "needs" | "poor";

/**
 * The standard Web Vitals thresholds: at or under the first a reading is good, over the second
 * poor. Milliseconds, and layout shift times 1000 for `cls`, as the record keeps it.
 */
export const VITAL_THRESHOLDS: Record<string, readonly [number, number]> = {
  lcp: [2500, 4000],
  inp: [200, 500],
  cls: [100, 250],
  fcp: [1800, 3000],
  ttfb: [800, 1800],
};

/** How a 75th percentile reads against its metric's thresholds; null for an unknown one. */
export function vitalRating(metric: string, value: number | null): VitalRating | null {
  const limits = VITAL_THRESHOLDS[metric];
  if (limits === undefined || value === null) return null;
  if (value <= limits[0]) return "good";
  return value <= limits[1] ? "needs" : "poor";
}

/** The pages and devices the per-page sections can show, busiest first. */
export function pageChoices(report: UsageReport): { pages: string[]; devices: string[] } {
  const weight = new Map<string, number>();
  const devices = new Map<string, number>();
  const add = (page: string, device: string, events: number) => {
    weight.set(page, (weight.get(page) ?? 0) + events);
    devices.set(device, (devices.get(device) ?? 0) + events);
  };
  for (const cell of report.behaviour.clicks) add(cell.page, cell.device, cell.events);
  for (const view of report.behaviour.scroll) add(view.page, view.device, view.events);
  const order = (map: Map<string, number>) =>
    [...map].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).map(([name]) => name);
  return { pages: order(weight), devices: order(devices) };
}

/** One page and device's scroll entry, or null when none was sent. */
export function scrollFor(report: UsageReport, page: string, device: string): UsageScroll | null {
  return (
    report.behaviour.scroll.find((entry) => entry.page === page && entry.device === device) ?? null
  );
}

export interface ZoneClicks {
  zone: string;
  clicks: number;
  rage: number;
  dead: number;
}

/** One page and device's clicks summed by zone, busiest first. */
export function clicksByZone(report: UsageReport, page: string, device: string): ZoneClicks[] {
  const zones = new Map<string, ZoneClicks>();
  for (const cell of report.behaviour.clicks) {
    if (cell.page !== page || cell.device !== device) continue;
    const zone = zones.get(cell.zone) ?? { zone: cell.zone, clicks: 0, rage: 0, dead: 0 };
    zone.clicks += cell.events;
    zone.rage += cell.marks.rage;
    zone.dead += cell.marks.dead;
    zones.set(cell.zone, zone);
  }
  return [...zones.values()].sort((a, b) => b.clicks - a.clicks || a.zone.localeCompare(b.zone));
}
