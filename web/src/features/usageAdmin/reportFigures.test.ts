import { describe, expect, it } from "vitest";

import { emptyUsageReportFixture, usageReportFixture } from "../../testSupport/usageReport";
import {
  clicksByZone,
  cumulativeDepth,
  funnel,
  pageChoices,
  reportIsEmpty,
  usageTotals,
  vitalRating,
} from "./reportFigures";

const depthOf = (entries: Record<string, number>) => ({
  ...Object.fromEntries(
    ["0", "10", "20", "30", "40", "50", "60", "70", "80", "90", "100"].map((d) => [d, 0]),
  ),
  ...entries,
});

describe("scroll depth, read as at least this far", () => {
  it("sums every bucket from each tenth up", () => {
    const rows = cumulativeDepth(depthOf({ "0": 20, "50": 80, "100": 100 }));
    expect(rows.map((row) => row.depth)).toEqual([10, 20, 30, 40, 50, 60, 70, 80, 90, 100]);
    expect(rows.map((row) => row.views)).toEqual([
      180, 180, 180, 180, 180, 100, 100, 100, 100, 100,
    ]);
    expect(rows[0]!.share).toBe(0.9);
    expect(rows[9]!.share).toBe(0.5);
  });

  it("never rises as the depth grows", () => {
    const rows = cumulativeDepth(depthOf({ "10": 3, "30": 7, "70": 1, "90": 4 }));
    for (let index = 1; index < rows.length; index += 1) {
      expect(rows[index]!.views).toBeLessThanOrEqual(rows[index - 1]!.views);
    }
    expect(rows.map((row) => row.views)).toEqual([15, 12, 12, 5, 5, 5, 5, 4, 4, 0]);
  });

  it("has no share for no views", () => {
    expect(cumulativeDepth(depthOf({})).every((row) => row.views === 0 && row.share === null)).toBe(
      true,
    );
  });
});

describe("speed ratings by the standard thresholds", () => {
  it.each([
    ["lcp", 2500, "good"],
    ["lcp", 2501, "needs"],
    ["lcp", 4000, "needs"],
    ["lcp", 4001, "poor"],
    ["inp", 200, "good"],
    ["inp", 500, "needs"],
    ["inp", 501, "poor"],
    ["cls", 100, "good"],
    ["cls", 250, "needs"],
    ["cls", 251, "poor"],
    ["fcp", 1800, "good"],
    ["fcp", 3000, "needs"],
    ["fcp", 3001, "poor"],
    ["ttfb", 800, "good"],
    ["ttfb", 1800, "needs"],
    ["ttfb", 1801, "poor"],
  ] as const)("%s at %i is %s", (metric, value, rating) => {
    expect(vitalRating(metric, value)).toBe(rating);
  });

  it("rates nothing it cannot", () => {
    expect(vitalRating("lcp", null)).toBeNull();
    expect(vitalRating("fid", 10)).toBeNull();
  });
});

describe("the totals", () => {
  it("are the report's own shares", () => {
    expect(usageTotals(usageReportFixture())).toEqual({
      visits: 321,
      events: 6234,
      claimShare: 0.7,
      returningShare: 0.5,
      phoneShare: 0.75,
      frustrationShare: 15 / 106,
    });
  });

  it("have no share where the whole is nothing", () => {
    const totals = usageTotals(emptyUsageReportFixture());
    expect(totals.claimShare).toBeNull();
    expect(totals.returningShare).toBeNull();
    expect(totals.phoneShare).toBeNull();
    expect(totals.frustrationShare).toBeNull();
    expect(reportIsEmpty(emptyUsageReportFixture())).toBe(true);
    expect(reportIsEmpty(usageReportFixture())).toBe(false);
  });
});

describe("the funnel", () => {
  it("counts each step's visits against the visits that opened a page", () => {
    expect(funnel(usageReportFixture())).toEqual([
      { step: "open", visits: 300, share: 1 },
      { step: "picker_shown", visits: 120, share: 0.4 },
      { step: "picker_claimed", visits: 90, share: 0.3 },
      { step: "tool", visits: 222, share: 0.74 },
      { step: "device_solve", visits: 13, share: 13 / 300 },
    ]);
  });
});

describe("one page and device", () => {
  it("offers the busiest page and device first", () => {
    expect(pageChoices(usageReportFixture())).toEqual({
      pages: ["member", "league"],
      devices: ["phone", "desktop"],
    });
  });

  it("sums the clicks by tool and zone", () => {
    expect(clicksByZone(usageReportFixture(), "member", "phone")).toEqual([
      { zone: "decision", tool: "week", clicks: 50, rage: 6, dead: 4 },
      { zone: "pitch", tool: "week", clicks: 25, rage: 0, dead: 5 },
      { zone: "decision", tool: "chips", clicks: 7, rage: 0, dead: 0 },
      { zone: "page", tool: "week", clicks: 3, rage: 0, dead: 0 },
    ]);
    expect(clicksByZone(usageReportFixture(), "member", "tablet")).toEqual([]);
  });

  it("keeps an older report's rows, with no tool, in rows of their own", () => {
    const report = usageReportFixture();
    report.behaviour.clicks = report.behaviour.clicks.map((cell) => ({ ...cell, tool: null }));
    expect(clicksByZone(report, "member", "phone")[0]).toEqual({
      zone: "decision",
      tool: null,
      clicks: 57,
      rage: 6,
      dead: 4,
    });
  });
});
