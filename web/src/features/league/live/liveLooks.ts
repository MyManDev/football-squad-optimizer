/**
 * What the visitor last saw of a member's live week, kept in this browser so that coming back
 * to LIVE (from another page, a reload, a new tab) moves what changed since and tells it under
 * "Son bakıştan beri" (the synthesis of 2026-11-11, section 3.4: a reopen against the last
 * look). Nothing leaves the browser.
 *
 * At most 24 looks are kept, one per member and week, the newest reads: the visitor's own week
 * outlasts the rivals they look at. A look is replaced only by one at least as new, whichever tab
 * kept it. Every read and write of the storage is in try/catch: where the browser keeps nothing
 * (private browsing, full or blocked storage) the looks are kept in memory for the page's life.
 */

import type { LiveRecap, RecapMarks } from "./liveBoard";
import type { DuelLook, LiveLook, RowLook } from "./liveMotion";

export const LOOKS_KEY = "squadopt.liveLook";
const VERSION = 1;
/** The looks kept, a member's week each, the newest reads. */
export const KEPT_LOOKS = 24;

interface StoredMarks {
  identity: string;
  time: number;
  takes: [number, number][];
  counts: [string, number][];
  detailed: boolean;
  cards: number[];
}

interface KeptLook {
  look: LiveLook;
  marks: StoredMarks;
}

const memory = new Map<string, KeptLook>();

const isNumber = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

function isRow(value: unknown): value is RowLook {
  if (typeof value !== "object" || value === null) return false;
  const row = value as Record<string, unknown>;
  return (
    isNumber(row.pick) &&
    isNumber(row.points) &&
    isNumber(row.shown) &&
    isNumber(row.take) &&
    isNumber(row.multiplier) &&
    isNumber(row.minutes) &&
    (row.appearance === undefined || isNumber(row.appearance)) &&
    isNumber(row.place) &&
    typeof row.started === "boolean" &&
    typeof row.counted === "boolean" &&
    typeof row.group === "string" &&
    (row.state === null || typeof row.state === "string") &&
    (row.autosub === null || row.autosub === "in" || row.autosub === "out") &&
    (row.armband === null || row.armband === "captain" || row.armband === "vice")
  );
}

function isDuel(value: unknown): value is DuelLook {
  if (typeof value !== "object" || value === null) return false;
  const duel = value as Record<string, unknown>;
  return (
    isNumber(duel.rivalId) &&
    isNumber(duel.rivalNet) &&
    isNumber(duel.memberNet) &&
    isNumber(duel.margin)
  );
}

function isKept(value: unknown): value is KeptLook {
  if (typeof value !== "object" || value === null) return false;
  const { look, marks } = value as {
    look?: Record<string, unknown>;
    marks?: Record<string, unknown>;
  };
  if (typeof look !== "object" || look === null || typeof marks !== "object" || marks === null) {
    return false;
  }
  return (
    typeof look.key === "string" &&
    typeof look.sourceTime === "string" &&
    isNumber(look.time) &&
    isNumber(look.net) &&
    typeof look.playing === "boolean" &&
    typeof look.rows === "object" &&
    look.rows !== null &&
    Object.values(look.rows).every(isRow) &&
    (look.rival === null || isDuel(look.rival)) &&
    typeof marks.identity === "string" &&
    isNumber(marks.time) &&
    typeof marks.detailed === "boolean" &&
    Array.isArray(marks.takes) &&
    marks.takes.every((pair) => Array.isArray(pair) && isNumber(pair[0]) && isNumber(pair[1])) &&
    Array.isArray(marks.counts) &&
    marks.counts.every(
      (pair) => Array.isArray(pair) && typeof pair[0] === "string" && isNumber(pair[1]),
    ) &&
    Array.isArray(marks.cards) &&
    marks.cards.every(isNumber)
  );
}

/** The looks the browser keeps; none where it keeps nothing or keeps something else. */
function stored(): KeptLook[] {
  try {
    const text = globalThis.localStorage?.getItem(LOOKS_KEY);
    if (text === null || text === undefined) return [];
    const parsed = JSON.parse(text) as { v?: unknown; looks?: unknown };
    if (parsed.v !== VERSION || !Array.isArray(parsed.looks)) return [];
    return parsed.looks.filter(isKept);
  } catch {
    return [];
  }
}

/**
 * The newest look kept for `key`: this tab's, or the one the browser keeps, which another tab
 * may have kept since.
 */
function newest(key: string): KeptLook | undefined {
  const mine = memory.get(key);
  const theirs = stored().find((entry) => entry.look.key === key);
  if (mine === undefined || theirs === undefined) return mine ?? theirs;
  return theirs.look.time > mine.look.time ? theirs : mine;
}

/** The look last kept for `key`, with the recap's marks as they were then. */
export function readLook(key: string): { look: LiveLook; marks: RecapMarks } | null {
  const kept = newest(key);
  if (kept === undefined) return null;
  const { marks } = kept;
  return {
    look: kept.look,
    marks: {
      identity: marks.identity,
      time: marks.time,
      takes: new Map(marks.takes),
      counts: new Map(marks.counts),
      detailed: marks.detailed,
      cards: new Set(marks.cards),
    },
  };
}

/** Keeps `look` with the recap's marks, unless a newer look of the same week is kept. */
export function keepLook(look: LiveLook, recap: LiveRecap): void {
  // Another tab may have kept a newer look of the week since this one last did.
  const before = newest(look.key);
  if (before !== undefined && before.look.time > look.time) return;
  const entry: KeptLook = {
    look,
    marks: {
      identity: recap.identity,
      time: recap.time,
      takes: [...recap.takes],
      counts: [...recap.counts],
      detailed: recap.detailed,
      cards: [...recap.cards],
    },
  };
  memory.set(look.key, entry);
  try {
    const storage = globalThis.localStorage;
    if (storage === undefined) return;
    const others = stored().filter((kept) => kept.look.key !== look.key);
    const looks = [entry, ...others].sort((a, b) => b.look.time - a.look.time).slice(0, KEPT_LOOKS);
    storage.setItem(LOOKS_KEY, JSON.stringify({ v: VERSION, looks }));
  } catch {
    // Kept in memory for the page's life.
  }
}

/** For tests: the looks kept in memory are forgotten; the storage is the test's to clear. */
export function forgetLooks(): void {
  memory.clear();
}
