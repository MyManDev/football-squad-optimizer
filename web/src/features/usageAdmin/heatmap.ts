/**
 * The heatmap mode's arithmetic (ADR 0016): which of a report's clicks a place (page and tool),
 * device and mark select, where each cell of a zone's 20 by 20 grid lies over the zone's box in
 * the document, and the cell's colour. The box is the element's current one, so the drawing
 * follows the layout the person is looking at. Also the mode's two reads, kept for the page's
 * life.
 *
 * Clicks in no zone (`page`) are counted, never drawn: their cell is of a grid over the whole
 * document, whose size differs between tools and window heights, so it lands on nothing.
 */
import type { UsagePlace } from "../../data/usage";
import {
  rangeEnding,
  readUsageAdminMe,
  readUsageReport,
  type UsageAdminAnswer,
  type UsageClickCell,
  type UsageReport,
} from "../../data/usageAdmin";

/** The cells a zone's box is cut into along each side, as the record cuts them. */
export const GRID = 20;

export type HeatMark = "all" | "rage" | "dead";
export type HeatDevice = "phone" | "desktop" | "tablet";
export type HeatDays = 7 | 28;

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** A zone's counts by cell, for one place, device and mark. */
export type ZoneCounts = Map<string, Map<number, number>>;

/** The zone of a click that had no `data-zone` around it. */
export const NO_ZONE = "page";

/**
 * What one place, device and mark select: counts by zone and cell, the busiest cell and the
 * sum, over the zones that are drawn; the clicks in no zone, counted apart; and whether any
 * row came without a tool (an older Worker's), so other tools' clicks may be among them.
 */
export interface CellSelection {
  zones: ZoneCounts;
  max: number;
  total: number;
  outside: number;
  untooled: boolean;
}

/** The count a mark reads from one cell's entry. */
function countOf(cell: UsageClickCell, mark: HeatMark): number {
  return mark === "all" ? cell.events : cell.marks[mark];
}

/**
 * The report's clicks for one place, device and mark, by zone and cell; zero cells left out.
 * A row is the place's when its page and its tool are the place's: every tool of a member's
 * page is page `member`, so the page alone would draw one tool's clicks over another. A row
 * with no tool (from a Worker before 2026-11-23) is kept on its page alone, as before, since
 * which tool it came from is not known; `untooled` says so.
 */
export function selectCells(
  clicks: readonly UsageClickCell[],
  place: UsagePlace,
  device: string,
  mark: HeatMark,
): CellSelection {
  const zones: ZoneCounts = new Map();
  let max = 0;
  let total = 0;
  let outside = 0;
  let untooled = false;
  for (const cell of clicks) {
    if (cell.page !== place.page || cell.device !== device) continue;
    if (cell.tool !== null && cell.tool !== place.tool) continue;
    const count = countOf(cell, mark);
    if (count <= 0) continue;
    if (cell.tool === null) untooled = true;
    if (cell.zone === NO_ZONE) {
      outside += count;
      continue;
    }
    const cells = zones.get(cell.zone) ?? new Map<number, number>();
    const sum = (cells.get(cell.cell) ?? 0) + count;
    cells.set(cell.cell, sum);
    zones.set(cell.zone, cells);
    max = Math.max(max, sum);
    total += count;
  }
  return { zones, max, total, outside, untooled };
}

/** A box in the viewport moved to the document: the scroll offsets added. */
export function documentBox(
  rect: Pick<DOMRect, "left" | "top" | "width" | "height">,
  scrollX: number,
  scrollY: number,
): Box {
  return {
    left: rect.left + scrollX,
    top: rect.top + scrollY,
    width: rect.width,
    height: rect.height,
  };
}

/** Where one cell, row times 20 plus column, lies over a box. */
export function cellRect(box: Box, cell: number): Box {
  const width = box.width / GRID;
  const height = box.height / GRID;
  return {
    left: box.left + (cell % GRID) * width,
    top: box.top + Math.floor(cell / GRID) * height,
    width,
    height,
  };
}

/** The colour of a share of the busiest cell: blue, then yellow, then red. */
export function heatColour(share: number): string {
  const t = Math.sqrt(Math.min(1, Math.max(0, share)));
  const stops: [number, number, number][] = [
    [37, 99, 235],
    [250, 204, 21],
    [220, 38, 38],
  ];
  const [from, to, along] =
    t <= 0.5 ? [stops[0]!, stops[1]!, t * 2] : [stops[1]!, stops[2]!, t * 2 - 1];
  const mix = from.map((value, index) => Math.round(value + (to[index]! - value) * along));
  return `rgb(${mix.join(", ")})`;
}

export interface HeatCell extends Box {
  key: string;
  count: number;
  colour: string;
}

/** A zone's cells over its box, each coloured by the square root of its share of `max`. */
export function zoneCells(
  zone: string,
  box: Box,
  cells: Map<number, number>,
  max: number,
): HeatCell[] {
  if (box.width <= 0 || box.height <= 0 || max <= 0) return [];
  return [...cells].map(([cell, count]) => ({
    ...cellRect(box, cell),
    key: `${zone}:${box.left}:${box.top}:${cell}`,
    count,
    colour: heatColour(count / max),
  }));
}

/** Whether an element is drawn: it has a box and is not hidden by `visibility`. */
function drawn(element: Element): boolean {
  const box = element.getBoundingClientRect();
  if (box.width <= 0 || box.height <= 0) return false;
  return typeof element.checkVisibility === "function"
    ? element.checkVisibility({ visibilityProperty: true })
    : true;
}

/**
 * Every cell to draw, over the boxes the zones have now: each drawn `[data-zone]` element's
 * grid over its own box. A word no element carries (a zone of another layout, or a retired
 * word) draws nothing, and neither do clicks in no zone. The layer is hidden while the
 * document is measured, so its own size never counts in a box.
 */
export function measureCells(selection: CellSelection, layer: HTMLElement | null): HeatCell[] {
  if (layer !== null) layer.hidden = true;
  try {
    const cells: HeatCell[] = [];
    for (const element of document.querySelectorAll("[data-zone]")) {
      const zone = element.getAttribute("data-zone") ?? "";
      const counts = zone === NO_ZONE ? undefined : selection.zones.get(zone);
      if (counts === undefined || !drawn(element)) continue;
      const box = documentBox(element.getBoundingClientRect(), window.scrollX, window.scrollY);
      cells.push(...zoneCells(zone, box, counts, selection.max));
    }
    return cells;
  } finally {
    if (layer !== null) layer.hidden = false;
  }
}

// ---- The two reads, once each for the page's life ----

let me: Promise<UsageAdminAnswer<true>> | null = null;
const reports = new Map<HeatDays, Promise<UsageAdminAnswer<UsageReport>>>();

/** Whether this person may read the record, asked once a page load. */
export function adminOnce(): Promise<UsageAdminAnswer<true>> {
  me ??= readUsageAdminMe();
  return me;
}

/**
 * The report for the last 7 or 28 UTC days, read once a page load for each. A read that did
 * not succeed is forgotten, so choosing the range again asks again.
 */
export function reportOnce(days: HeatDays): Promise<UsageAdminAnswer<UsageReport>> {
  let read = reports.get(days);
  if (read === undefined) {
    const started = readUsageReport(rangeEnding(days));
    read = started;
    reports.set(days, started);
    void started.then((answer) => {
      if (answer.state !== "ok" && reports.get(days) === started) reports.delete(days);
    });
  }
  return read;
}

/** For tests: forgets both reads, as a new page load would. */
export function forgetHeatmapReads(): void {
  me = null;
  reports.clear();
}
