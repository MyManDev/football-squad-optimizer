import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../../../fixtures/weeklySuggestionHistory.json";
import { LeagueDataError, LeagueDataMissing } from "../dataErrors";
import { checkedHistory, loadSuggestionHistory, type SuggestionHistory } from "./historyData";

afterEach(() => vi.unstubAllGlobals());
const document = () => structuredClone(fixture) as SuggestionHistory;

describe("recorded weekly history", () => {
  it("accepts the exact Python scorer fixture and preserves its negative difference", () => {
    const result = checkedHistory(fixture, 101);
    expect(result.payload.weeks[0].net_difference).toBe(-2);
    expect(result.payload.weeks[0].players).toHaveLength(15);
  });

  it.each<(value: SuggestionHistory) => void>([
    (value) => {
      value.payload.entry_id = 202;
    },
    (value) => {
      Object.assign(value.payload, { league_id: 123 });
    },
    (value) => {
      value.payload.weeks[0].status = "unsettled";
    },
    (value) => {
      value.payload.weeks[0].suggested!.net_points = 999;
    },
    (value) => {
      value.payload.weeks[0].net_difference = 99;
    },
    (value) => {
      value.payload.weeks[0].actual = null;
    },
    (value) => {
      value.payload.weeks[0].players[0].counted_points = 999;
    },
    (value) => {
      value.payload.weeks[0].players[0].expected_points = Infinity;
    },
    (value) => {
      value.payload.weeks[0].players.pop();
    },
    (value) => {
      value.payload.weeks.push(value.payload.weeks[0]);
    },
    (value) => {
      value.payload.weeks[0].advice_generated_at_utc = value.payload.weeks[0].deadline_utc;
    },
    (value) => {
      value.payload.weeks[0].outcome_captured_at_utc =
        value.payload.weeks[0].advice_captured_at_utc;
    },
  ])("rejects inconsistent identity, points, timing or settlement (%#)", (mutate) => {
    const value = document();
    mutate(value);
    expect(() => checkedHistory(value, 101)).toThrow(LeagueDataError);
  });

  it("accepts an empty archive and an explicit unsettled record without scores", () => {
    const value = document();
    Object.assign(value.payload.weeks[0], {
      status: "unsettled",
      reason: "not_settled",
      suggested: null,
      actual: null,
      actual_reason: null,
      net_difference: null,
      players: [],
      outcome_snapshot_id: null,
      outcome_captured_at_utc: null,
    });
    expect(checkedHistory(value, 101).payload.weeks[0].status).toBe("unsettled");
    value.payload.weeks = [];
    expect(checkedHistory(value, 101).payload.weeks).toEqual([]);
  });

  it.each([404, 200])(
    "does not invent examples for missing files or SPA fallback (%s)",
    async (status) => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(new Response("<!doctype html><html></html>", { status })),
      );
      await expect(loadSuggestionHistory(101)).rejects.toBeInstanceOf(LeagueDataMissing);
    },
  );

  it("fails broken JSON as unreadable, and reads valid published data without a fixture fallback", async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(new Response("{broken"))
      .mockResolvedValueOnce(new Response(JSON.stringify(fixture)));
    vi.stubGlobal("fetch", fetch);
    await expect(loadSuggestionHistory(101)).rejects.toBeInstanceOf(LeagueDataError);
    await expect(loadSuggestionHistory(101)).resolves.toEqual(fixture);
    expect(fetch).toHaveBeenLastCalledWith(
      "/data/league/history/101.json",
      expect.objectContaining({ cache: "no-cache" }),
    );
  });
});
