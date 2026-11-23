import { afterEach, describe, expect, it, vi } from "vitest";

import { usageReportFixture } from "../../testSupport/usageReport";
import {
  adminOnce,
  cellRect,
  documentBox,
  forgetHeatmapReads,
  heatColour,
  measureCells,
  reportOnce,
  selectCells,
  zoneCells,
} from "./heatmap";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  forgetHeatmapReads();
  document.body.innerHTML = "";
});

const clicks = usageReportFixture().behaviour.clicks;

const WEEK = { page: "member", tool: "week" };

describe("the cells a choice selects", () => {
  it("keeps one page, tool and device, by zone and cell", () => {
    const { zones, max, total, untooled } = selectCells(clicks, WEEK, "phone", "all");
    expect([...zones.keys()]).toEqual(["decision", "pitch"]);
    expect([...zones.get("decision")!]).toEqual([
      [0, 40],
      [21, 10],
    ]);
    expect(max).toBe(40);
    expect(total).toBe(75);
    expect(untooled).toBe(false);
  });

  it("leaves another tool of the same page out", () => {
    // Every tool of a member's page is page `member`: the chips tool's click in the same
    // zone and cell is that tool's alone.
    const chips = selectCells(clicks, { page: "member", tool: "chips" }, "phone", "all");
    expect([...chips.zones.keys()]).toEqual(["decision"]);
    expect([...chips.zones.get("decision")!]).toEqual([[0, 7]]);
    expect(chips.total).toBe(7);
    expect(chips.outside).toBe(0);
    expect(selectCells(clicks, { page: "member", tool: "duel" }, "phone", "all").total).toBe(0);
  });

  it("counts the clicks in no zone apart and never draws them", () => {
    const { zones, total, outside } = selectCells(clicks, WEEK, "phone", "all");
    expect(zones.has("page")).toBe(false);
    expect(outside).toBe(3);
    expect(total).toBe(75);
    expect(selectCells(clicks, WEEK, "phone", "rage").outside).toBe(0);
  });

  it("keeps a row with no tool, from an older Worker, on its page alone, and says so", () => {
    const older = clicks.map((cell) => ({ ...cell, tool: null }));
    const chips = selectCells(older, { page: "member", tool: "chips" }, "phone", "all");
    expect([...chips.zones.get("decision")!]).toEqual([
      [0, 47],
      [21, 10],
    ]);
    expect(chips.total).toBe(82);
    expect(chips.outside).toBe(3);
    expect(chips.untooled).toBe(true);
    expect(selectCells(older, { page: "league", tool: "" }, "phone", "all").total).toBe(12);
  });

  it("reads a mark's own count and leaves zero cells out", () => {
    const rage = selectCells(clicks, WEEK, "phone", "rage");
    expect([...rage.zones.keys()]).toEqual(["decision"]);
    expect(rage.total).toBe(6);
    const dead = selectCells(clicks, WEEK, "phone", "dead");
    expect(dead.total).toBe(9);
    expect(dead.max).toBe(5);
  });
});

describe("a zone's box to its cells", () => {
  it("moves a viewport box to the document by the scroll offsets", () => {
    expect(documentBox({ left: 10, top: -50, width: 200, height: 100 }, 5, 300)).toEqual({
      left: 15,
      top: 250,
      width: 200,
      height: 100,
    });
  });

  it("cuts the box into a 20 by 20 grid, row times 20 plus column", () => {
    const box = { left: 100, top: 1000, width: 400, height: 200 };
    expect(cellRect(box, 0)).toEqual({ left: 100, top: 1000, width: 20, height: 10 });
    expect(cellRect(box, 21)).toEqual({ left: 120, top: 1010, width: 20, height: 10 });
    expect(cellRect(box, 19)).toEqual({ left: 480, top: 1000, width: 20, height: 10 });
    expect(cellRect(box, 399)).toEqual({ left: 480, top: 1190, width: 20, height: 10 });
  });

  it("colours each cell by the square root of its share of the busiest", () => {
    const cells = zoneCells(
      "decision",
      { left: 0, top: 0, width: 200, height: 200 },
      new Map([
        [0, 40],
        [21, 10],
      ]),
      40,
    );
    expect(
      cells.map(({ left, top, width, height, count }) => ({ left, top, width, height, count })),
    ).toEqual([
      { left: 0, top: 0, width: 10, height: 10, count: 40 },
      { left: 10, top: 10, width: 10, height: 10, count: 10 },
    ]);
    expect(cells[0]!.colour).toBe(heatColour(1));
    // sqrt(10 / 40) is a half: the middle of the scale.
    expect(cells[1]!.colour).toBe(heatColour(0.25));
    expect(heatColour(0.25)).toBe("rgb(250, 204, 21)");
  });

  it("runs blue, then yellow, then red", () => {
    expect(heatColour(0)).toBe("rgb(37, 99, 235)");
    expect(heatColour(1)).toBe("rgb(220, 38, 38)");
    expect(heatColour(7)).toBe("rgb(220, 38, 38)");
  });

  it("draws nothing over a box with no size", () => {
    expect(
      zoneCells("pitch", { left: 0, top: 0, width: 0, height: 50 }, new Map([[1, 2]]), 2),
    ).toEqual([]);
  });
});

describe("the live page", () => {
  function zone(word: string, box: { left: number; top: number; width: number; height: number }) {
    const element = document.createElement("section");
    element.setAttribute("data-zone", word);
    vi.spyOn(element, "getBoundingClientRect").mockReturnValue({
      ...box,
      right: box.left + box.width,
      bottom: box.top + box.height,
      x: box.left,
      y: box.top,
      toJSON: () => ({}),
    });
    document.body.append(element);
    return element;
  }

  it("draws each drawn zone over its box in the document, and nothing for clicks in no zone", () => {
    vi.stubGlobal("scrollX", 0);
    vi.stubGlobal("scrollY", 500);
    zone("decision", { left: 20, top: -100, width: 400, height: 400 });
    zone("pitch", { left: 0, top: 0, width: 0, height: 0 });
    zone("squad", { left: 0, top: 0, width: 100, height: 100 });
    // An element that names `page` is no zone's box either.
    zone("page", { left: 0, top: 0, width: 1000, height: 4000 });
    const selection = selectCells(clicks, WEEK, "phone", "all");
    expect(selection.outside).toBe(3);
    const layer = document.createElement("div");
    const cells = measureCells(selection, layer);
    expect(layer.hidden).toBe(false);
    expect(
      cells.map(({ left, top, width, height, count }) => [left, top, width, height, count]),
    ).toEqual([
      // The decision zone, 100 px above the viewport with the page scrolled 500 px.
      [20, 400, 20, 20, 40],
      [40, 420, 20, 20, 10],
    ]);
  });
});

describe("the mode's reads", () => {
  it("asks whether this is an admin once a page load", async () => {
    const fetch = vi.fn(async () =>
      Response.json({ contract_version: "usage_admin_v1", admin: true }),
    );
    vi.stubGlobal("fetch", fetch);
    await Promise.all([adminOnce(), adminOnce()]);
    await adminOnce();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("reads each range once, and asks again after a failure", async () => {
    const fetch = vi.fn(async () => Response.json(usageReportFixture()));
    vi.stubGlobal("fetch", fetch);
    await reportOnce(7);
    await reportOnce(7);
    await reportOnce(28);
    expect(fetch).toHaveBeenCalledTimes(2);
    forgetHeatmapReads();
    fetch.mockImplementationOnce(async () => Response.json({}, { status: 502 }));
    expect((await reportOnce(7)).state).toBe("failed");
    await Promise.resolve();
    expect((await reportOnce(7)).state).toBe("ok");
    expect(fetch).toHaveBeenCalledTimes(4);
  });
});
