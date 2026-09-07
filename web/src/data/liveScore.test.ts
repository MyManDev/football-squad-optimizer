import { describe, expect, it, vi, afterEach } from "vitest";
import { StaticDataClient } from "./client";
import { readLiveScore } from "./liveScore";
import { liveScoreFixture } from "../fixtures/liveScore";

afterEach(() => vi.unstubAllGlobals());

describe("live score reader", () => {
  it("reads the separate versioned document using the requested week", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(liveScoreFixture)));
    vi.stubGlobal("fetch", fetcher);
    const loaded = await new StaticDataClient("/data/").getLiveScore("2026-27", 1);
    expect(loaded.payload).toEqual(liveScoreFixture.payload);
    expect(fetcher).toHaveBeenCalledWith("/data/2026-27/gw01/live.json", { cache: "no-cache" });
  });

  it.each([
    { gameweek: 2 },
    { season: "2025-26" },
    { named_score: null },
    { net_score: 999 },
    { fixtures_finished: 11 },
    { bonus_confirmed: true },
    { captured_at_utc: "2027-01-01T00:00:00Z" },
    { status: "unavailable" },
  ])("rejects mismatched or incomplete values: %j", (patch) => {
    expect(() =>
      readLiveScore(
        { ...liveScoreFixture, payload: { ...liveScoreFixture.payload, ...patch } },
        "2026-27",
        1,
      ),
    ).toThrow();
  });

  it("refuses the old envelope version", () => {
    expect(() =>
      readLiveScore({ ...liveScoreFixture, contract_version: "ui_view_v1" }, "2026-27", 1),
    ).toThrow("live_score_v1");
  });
});
