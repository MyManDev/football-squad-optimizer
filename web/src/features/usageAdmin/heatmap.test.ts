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

describe("the cells a choice selects", () => {
  it("keeps one page and device, by zone and cell", () => {
    const { zones, max, total } = selectCells(clicks, "member", "phone", "all");
    expect([...zones.keys()]).toEqual(["decision", "pitch"]);
    expect([...zones.get("decision")!]).toEqual([
      [0, 40],
      [21, 10],
    ]);
    expect(max).toBe(40);
    expect(total).toBe(75);
  });

  it("reads a mark's own count and leaves zero cells out", () => {
    const rage = selectCells(clicks, "member", "phone", "rage");
    expect([...rage.zones.keys()]).toEqual(["decision"]);
    expect(rage.total).toBe(6);
    const dead = selectCells(clicks, "member", "phone", "dead");
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

  it("draws each drawn zone over its box in the document, and the page over the document", () => {
    vi.stubGlobal("scrollX", 0);
    vi.stubGlobal("scrollY", 500);
    zone("decision", { left: 20, top: -100, width: 400, height: 400 });
    zone("pitch", { left: 0, top: 0, width: 0, height: 0 });
    zone("squad", { left: 0, top: 0, width: 100, height: 100 });
    vi.spyOn(document.documentElement, "scrollWidth", "get").mockReturnValue(1000);
    vi.spyOn(document.documentElement, "scrollHeight", "get").mockReturnValue(4000);
    const selection = selectCells(
      [
        ...clicks,
        { ...clicks[0]!, zone: "page", cell: 399, events: 4, marks: { none: 4, rage: 0, dead: 0 } },
      ],
      "member",
      "phone",
      "all",
    );
    const layer = document.createElement("div");
    const cells = measureCells(selection, layer);
    expect(layer.hidden).toBe(false);
    expect(
      cells.map(({ left, top, width, height, count }) => [left, top, width, height, count]),
    ).toEqual([
      // The page's grid over the whole document, drawn first.
      [950, 3800, 50, 200, 4],
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
