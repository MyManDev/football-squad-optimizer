/**
 * The usage report's client (ADR 0016): one same-origin request that follows no redirect,
 * and every answer read as one of five states, with the report's shape checked first.
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { usageReportFixture } from "../testSupport/usageReport";
import {
  isUtcDay,
  parseUsageReport,
  rangeDays,
  rangeEnding,
  rangeIsReadable,
  readUsageAdminMe,
  readUsageReport,
} from "./usageAdmin";

afterEach(() => {
  vi.unstubAllGlobals();
});

function answer(response: Response | (() => Response | Promise<Response>)) {
  const fetch = vi.fn(async (_url: string, _init?: RequestInit) =>
    typeof response === "function" ? response() : response,
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

/** What a browser hands back for a redirect it was told not to follow. */
function opaqueRedirect(): Response {
  const response = new Response(null, { status: 200 });
  Object.defineProperty(response, "type", { value: "opaqueredirect" });
  Object.defineProperty(response, "status", { value: 0 });
  Object.defineProperty(response, "ok", { value: false });
  return response;
}

const RANGE = { from: "2026-11-10", to: "2026-11-16" };

describe("the report request", () => {
  it("asks the same origin with its cookies and follows no redirect", async () => {
    const fetch = answer(Response.json(usageReportFixture()));
    await readUsageReport(RANGE);
    const [url, init] = fetch.mock.calls[0]!;
    expect(url).toBe("/api/v1/usage/report?from=2026-11-10&to=2026-11-16");
    expect(init).toMatchObject({
      method: "GET",
      credentials: "same-origin",
      redirect: "manual",
      cache: "no-store",
    });
  });

  it("reads a report of the right shape", async () => {
    answer(Response.json(usageReportFixture()));
    const read = await readUsageReport(RANGE);
    expect(read.state).toBe("ok");
    if (read.state === "ok") expect(read.value).toEqual(usageReportFixture());
  });

  it.each([
    ["an Access redirect", () => opaqueRedirect(), "signed_out"],
    ["a 401", () => Response.json({ error: "x" }, { status: 401 }), "signed_out"],
    ["a 403", () => Response.json({ error: "access_refused" }, { status: 403 }), "refused"],
    [
      "a 503",
      () => Response.json({ error: "report_not_configured" }, { status: 503 }),
      "not_configured",
    ],
    ["a 502", () => Response.json({ error: "analytics_unavailable" }, { status: 502 }), "failed"],
    ["a 400", () => Response.json({ error: "range_too_long" }, { status: 400 }), "failed"],
    ["a page that is not JSON", () => new Response("<!doctype html><title>x</title>"), "failed"],
    ["JSON that is not a report", () => Response.json({ events: "many" }), "failed"],
  ] as const)("reads %s as %s", async (_name, response, state) => {
    answer(response);
    expect((await readUsageReport(RANGE)).state).toBe(state);
  });

  it("reads a network failure as failed, never throwing", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("Failed to fetch");
      }),
    );
    await expect(readUsageReport(RANGE)).resolves.toEqual({ state: "failed" });
  });
});

describe("the admin check", () => {
  it("asks /report/me and reads its yes", async () => {
    const fetch = answer(Response.json({ contract_version: "usage_admin_v1", admin: true }));
    await expect(readUsageAdminMe()).resolves.toEqual({ state: "ok", value: true });
    expect(fetch.mock.calls[0]![0]).toBe("/api/v1/usage/report/me");
  });

  it.each([
    [() => opaqueRedirect(), "signed_out"],
    [() => Response.json({ error: "access_refused" }, { status: 403 }), "refused"],
    [() => Response.json({ error: "report_not_configured" }, { status: 503 }), "not_configured"],
    [() => Response.json({ contract_version: "usage_admin_v2", admin: true }), "failed"],
    [() => Response.json({ contract_version: "usage_admin_v1", admin: false }), "failed"],
    [() => new Response("not json"), "failed"],
  ] as const)("reads every other answer as a no (%#)", async (response, state) => {
    answer(response);
    expect((await readUsageAdminMe()).state).toBe(state);
  });
});

describe("the report's shape", () => {
  it("fills a word map's missing words with zero", () => {
    const report = usageReportFixture() as unknown as Record<string, any>;
    delete report.behaviour.scroll[0].depth["30"];
    delete report.behaviour.clicks[0].marks.dead;
    const parsed = parseUsageReport(report);
    expect(parsed?.behaviour.scroll[0]!.depth["30"]).toBe(0);
    expect(parsed?.behaviour.clicks[0]!.marks.dead).toBe(0);
  });

  it("reads a row's tool, and a row with none as an older Worker's (null)", () => {
    const report = usageReportFixture() as unknown as Record<string, any>;
    delete report.behaviour.clicks[1].tool;
    delete report.behaviour.frustration[0].tool;
    const parsed = parseUsageReport(report)!;
    expect(parsed.behaviour.clicks.map((cell) => cell.tool)).toEqual([
      "week",
      null,
      "week",
      "chips",
      "week",
      "",
      "week",
    ]);
    expect(parsed.behaviour.frustration[0]!.tool).toBeNull();
    expect(parsed.behaviour.frustration[1]!.tool).toBe("week");
  });

  it.each<[string, (report: Record<string, any>) => void]>([
    ["a missing list", (report) => delete report.tools],
    ["a tool that is not a word", (report) => (report.behaviour.clicks[0].tool = 3)],
    ["a negative count", (report) => (report.visits = -1)],
    ["a count as text", (report) => (report.pages[0].visits = "3")],
    ["a cell past the grid", (report) => (report.behaviour.clicks[0].cell = 400)],
    ["a rating share over one", (report) => (report.behaviour.vitals[0].ratings.good = 2)],
    ["no behaviour", (report) => delete report.behaviour],
    ["arrivals as a list", (report) => (report.behaviour.arrivals = [])],
  ])("refuses %s", (_name, spoil) => {
    const report = usageReportFixture() as unknown as Record<string, any>;
    spoil(report);
    expect(parseUsageReport(report)).toBeNull();
  });

  it("refuses what is not an object at all", () => {
    for (const value of [null, 3, "report", []]) expect(parseUsageReport(value)).toBeNull();
  });
});

describe("ranges of UTC days", () => {
  const now = new Date("2026-11-16T23:30:00Z");

  it("ends today and counts both ends", () => {
    expect(rangeEnding(1, now)).toEqual({ from: "2026-11-16", to: "2026-11-16" });
    expect(rangeEnding(7, now)).toEqual({ from: "2026-11-10", to: "2026-11-16" });
    expect(rangeEnding(28, now)).toEqual({ from: "2026-10-20", to: "2026-11-16" });
    expect(rangeDays(rangeEnding(28, now))).toBe(28);
  });

  it("takes the day in UTC, not the browser's zone", () => {
    expect(rangeEnding(1, new Date("2026-11-17T00:30:00+03:00")).to).toBe("2026-11-16");
  });

  it("holds what the Worker takes", () => {
    expect(rangeIsReadable({ from: "2026-08-17", to: "2026-11-16" }, now)).toBe(true);
    expect(rangeIsReadable({ from: "2026-08-16", to: "2026-11-16" }, now)).toBe(false);
    expect(rangeIsReadable({ from: "2026-11-16", to: "2026-11-17" }, now)).toBe(false);
    expect(rangeIsReadable({ from: "2026-11-16", to: "2026-11-15" }, now)).toBe(false);
    expect(rangeIsReadable({ from: "", to: "2026-11-15" }, now)).toBe(false);
    expect(isUtcDay("2026-02-30")).toBe(false);
  });
});
