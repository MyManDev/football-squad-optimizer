/**
 * The last look kept in the browser: read back with the recap's marks, never replaced by an
 * older one from any tab, at most 24 member-weeks, and kept in memory where the browser keeps
 * nothing.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import { liveBeats } from "../../../testSupport/liveBeats";
import { advanceRecap, liveBoard, type LiveRecap } from "./liveBoard";
import { KEPT_LOOKS, LOOKS_KEY, forgetLooks, keepLook, readLook } from "./liveLooks";
import { lookOf, type LiveLook } from "./liveMotion";

afterEach(() => {
  forgetLooks();
  localStorage.clear();
  vi.restoreAllMocks();
});

function looked(): { look: LiveLook; recap: LiveRecap } {
  let recap: LiveRecap | null = null;
  let look: LiveLook | null = null;
  for (const beat of liveBeats().slice(0, 3)) {
    const board = liveBoard(beat.input)!;
    recap = advanceRecap(recap, board);
    look = lookOf(board, { rivalId: 7, rivalNet: board.net - 2, memberNet: board.net, margin: 2 });
  }
  return { look: look!, recap: recap! };
}

/** `look` as another week, at `time`. */
const weekAt = (look: LiveLook, week: number, time: number): LiveLook => ({
  ...look,
  key: `2026-27:101:${week}`,
  time,
  sourceTime: new Date(time).toISOString(),
});

/** `look` as another member's, the same week, at `time`. */
const memberAt = (look: LiveLook, entry: number, time: number): LiveLook => ({
  ...look,
  key: `2026-27:${entry}:10`,
  time,
  sourceTime: new Date(time).toISOString(),
});

describe("the last look", () => {
  it("is none where nothing was kept", () => {
    expect(readLook("2026-27:101:10")).toBeNull();
  });

  it("comes back with the recap's marks, also after the page's memory is gone", () => {
    const { look, recap } = looked();
    keepLook(look, recap);
    forgetLooks();
    const kept = readLook(look.key)!;
    expect(kept.look).toEqual(look);
    expect(kept.marks.identity).toBe(recap.identity);
    expect(kept.marks.takes).toEqual(recap.takes);
    expect(kept.marks.counts).toEqual(recap.counts);
    expect(kept.marks.cards).toEqual(recap.cards);
    expect(kept.marks.detailed).toBe(recap.detailed);
  });

  it("is never replaced by an older look of the same week", () => {
    const { look, recap } = looked();
    keepLook(look, recap);
    keepLook(weekAt(look, 10, look.time - 60_000), recap);
    forgetLooks();
    expect(readLook(look.key)!.look.time).toBe(look.time);
  });

  it("is never replaced by an older look from a tab that did not see the newer one", () => {
    const { look, recap } = looked();
    keepLook(look, recap);
    // Another tab, whose memory holds nothing of this week, keeps the read before.
    forgetLooks();
    keepLook(weekAt(look, 10, look.time - 60_000), recap);
    forgetLooks();
    expect(readLook(look.key)!.look.time).toBe(look.time);
  });

  it("is never replaced by an older look this tab still holds, when another tab kept a newer", () => {
    const { look, recap } = looked();
    const older = weekAt(look, 10, look.time - 60_000);
    // Another tab keeps the newer read; its text is what the browser holds.
    keepLook(look, recap);
    const theirs = localStorage.getItem(LOOKS_KEY)!;
    forgetLooks();
    localStorage.clear();
    // This tab saw only the read before, and keeps it again (a look clearing its recap).
    keepLook(older, recap);
    localStorage.setItem(LOOKS_KEY, theirs);
    keepLook(older, recap);
    expect(readLook(look.key)!.look.time).toBe(look.time);
    forgetLooks();
    expect(readLook(look.key)!.look.time).toBe(look.time);
  });

  it("keeps the visitor's own week while they look at four rivals in it", () => {
    const { look, recap } = looked();
    keepLook(look, recap);
    for (const entry of [102, 103, 104, 105]) {
      keepLook(memberAt(look, entry, look.time + entry * 60_000), recap);
    }
    forgetLooks();
    expect(readLook(look.key)).not.toBeNull();
  });

  it("keeps the newest member-weeks, at most 24", () => {
    const { look, recap } = looked();
    for (let week = 1; week <= KEPT_LOOKS + 1; week += 1) {
      keepLook(weekAt(look, week, look.time + week * 60_000), recap);
    }
    forgetLooks();
    expect(readLook("2026-27:101:1")).toBeNull();
    for (let week = 2; week <= KEPT_LOOKS + 1; week += 1) {
      expect(readLook(`2026-27:101:${week}`)).not.toBeNull();
    }
    const stored = JSON.parse(localStorage.getItem(LOOKS_KEY)!) as { looks: unknown[] };
    expect(stored.looks).toHaveLength(KEPT_LOOKS);
  });

  it("is kept in memory where the browser's storage throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const { look, recap } = looked();
    expect(() => keepLook(look, recap)).not.toThrow();
    expect(readLook(look.key)!.look).toEqual(look);
  });

  it("ignores what is not a look of this version", () => {
    const { look } = looked();
    for (const text of [
      "{",
      JSON.stringify({ v: 2, looks: [] }),
      JSON.stringify({
        v: 1,
        looks: [{ look: { ...look, rows: { 1: { pick: "x" } } }, marks: {} }],
      }),
    ]) {
      localStorage.setItem(LOOKS_KEY, text);
      expect(readLook(look.key)).toBeNull();
    }
  });
});
