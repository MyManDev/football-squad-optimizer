/**
 * Where the visitor reads on LIVE: the part kept where it was when a change above it moves it,
 * found below the phone bar, or above it where nothing is below, never a row the read takes to
 * another group, and the next one where a part read is taken away.
 */

import { describe, expect, it } from "vitest";

import { keepBy, readingAnchors } from "./livePlace";

const BAR = 56;
const none = () => false;

describe("where the visitor reads", () => {
  it("is nowhere while the groups' top is in sight", () => {
    expect(readingAnchors([["row:1", 300]], BAR, 120, none)).toEqual([]);
  });

  it("is the first part wholly below the bar, then the next ones down", () => {
    const tops = [
      ["group:playing", 20],
      ["row:10", 50],
      ["row:1", 106],
      ["group:upcoming", 70],
      ["after", 400],
    ] as const;
    expect(readingAnchors(tops, BAR, -200, none).map(({ part }) => part)).toEqual([
      "group:upcoming",
      "row:1",
      "after",
      "row:10",
      "group:playing",
    ]);
  });

  it("is never a row the read takes to another group", () => {
    const tops = [
      ["row:6", 60],
      ["row:7", 116],
    ] as const;
    const anchors = readingAnchors(tops, BAR, -200, (part) => part === "row:6");
    expect(anchors[0]!.part).toBe("row:7");
  });

  it("is the part the bar's line falls in where every part starts above it, as Farklar read", () => {
    // A phone on its side: no bar, and the visitor reads inside an open Farklar.
    const tops = [
      ["row:15", -620],
      ["group:bench", -700],
      ["after", -180],
    ] as const;
    expect(readingAnchors(tops, 0, -1400, none)[0]).toEqual({ part: "after", top: -180 });
  });
});

describe("how far the page scrolls to keep it", () => {
  it("by how far the part read moved", () => {
    const anchors = [{ part: "row:9", top: 64 }];
    expect(keepBy(anchors, new Map([["row:9", 104]]))).toBe(40);
    expect(keepBy(anchors, new Map([["row:9", 64.4]]))).toBe(0);
  });

  it("by the next part where the read took away the one read, as a group it emptied", () => {
    const anchors = [
      { part: "group:upcoming", top: 60 },
      { part: "group:finished", top: 300 },
    ];
    const now = new Map([["group:finished", 258]]);
    expect(keepBy(anchors, now)).toBe(-42);
  });

  it("not at all where nothing read is left", () => {
    expect(keepBy([{ part: "row:1", top: 60 }], new Map())).toBe(0);
  });
});
