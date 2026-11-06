import { afterEach, describe, expect, it, vi } from "vitest";
import fixture from "../../../fixtures/weeklySuggestionHistory.json";
import rows from "../../../fixtures/recordedPlanRows.json";
import { createLeagueTree } from "../data";
import { LeagueDataError, LeagueDataMissing } from "../dataErrors";
import { EXAMPLE_LEAGUE, exampleTree } from "../../../testSupport/league";
import { checkedHistory, loadSuggestionHistory, type SuggestionHistory } from "./historyData";

afterEach(() => vi.unstubAllGlobals());
const document = () => structuredClone(fixture) as SuggestionHistory;

describe("recorded weekly history", () => {
  it("accepts optional archived plans and preserves absent settings", () => {
    const value = document();
    Object.assign(value.payload.weeks[0], { recorded_plans: structuredClone(rows) });
    const plans = checkedHistory(value, 101).payload.weeks[0].recorded_plans!;
    expect(plans).toEqual(rows);
    expect(plans[0].top100_weight).toBeUndefined();
    expect(plans[0].managers_word).toBeUndefined();
  });
  it.each([
    { managers_word: false },
    { moves: [{ player_out: 12, player_in: null }] },
    { published_path: "advice/202/saf-puan/1.json" },
  ])("refuses invalid recorded row %j", (change) => {
    const value = document();
    Object.assign(value.payload.weeks[0], { recorded_plans: [{ ...rows[0], ...change }] });
    expect(() => checkedHistory(value, 101)).toThrow(LeagueDataError);
  });
  it("accepts the exact Python scorer fixture and preserves its negative difference", () => {
    const result = checkedHistory(fixture, 101);
    expect(result.payload.weeks[0].net_difference).toBe(-2);
    expect(result.payload.weeks[0].players).toHaveLength(15);
  });
  it.each([{ top100_weight: 7 }, { strategy: "future-strategy" }])(
    "drops only an unsupported plan %j",
    (change) => {
      const value = document();
      Object.assign(value.payload.weeks[0], {
        recorded_plans: [rows[0], { ...rows[1], ...change }],
      });
      const result = checkedHistory(value, 101);
      expect(result.payload.weeks[0].recorded_plans).toEqual([rows[0]]);
      expect(result.payload.weeks[0].suggested).toEqual(fixture.payload.weeks[0].suggested);
    },
  );

  it.each<(value: SuggestionHistory) => void>([
    (value) => {
      value.payload.entry_id = 202;
    },
    (value) => {
      // Another league's history, where the tree's league is asked for.
      Object.assign(value.payload, { league_id: 123 });
    },
    (value) => {
      Object.assign(value.payload, { league_id: 0 });
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
    expect(() => checkedHistory(value, 101, 352490)).toThrow(LeagueDataError);
  });

  it("reads a league's history for whichever league the tree is", () => {
    const value = document();
    Object.assign(value.payload, { league_id: 123 });
    expect(checkedHistory(value, 101, 123).payload.league_id).toBe(123);
    expect(checkedHistory(value, 101).payload.league_id).toBe(123);
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
        vi
          .fn()
          .mockImplementation(() =>
            Promise.resolve(new Response("<!doctype html><html></html>", { status })),
          ),
      );
      await expect(loadSuggestionHistory(exampleTree, 101)).rejects.toBeInstanceOf(
        LeagueDataMissing,
      );
    },
  );

  it("fails broken JSON as unreadable, and reads valid published data without a fixture fallback", async () => {
    const published = vi
      .fn()
      .mockResolvedValueOnce(new Response("{broken"))
      .mockResolvedValueOnce(new Response(JSON.stringify(fixture)));
    const fetch = vi.fn((url: string) =>
      url.includes("/requested/")
        ? Promise.resolve(new Response("", { status: 404 }))
        : published(),
    );
    vi.stubGlobal("fetch", fetch);
    await expect(loadSuggestionHistory(exampleTree, 101)).rejects.toBeInstanceOf(LeagueDataError);
    await expect(loadSuggestionHistory(exampleTree, 101)).resolves.toEqual(fixture);
    expect(fetch).toHaveBeenCalledWith(
      "/data/league/history/101.json",
      expect.objectContaining({ cache: "no-cache" }),
    );
  });

  it("reads a league published under the directory at its own path", async () => {
    const fetch = vi.fn((url: string) =>
      Promise.resolve(
        url.includes("/requested/")
          ? new Response("", { status: 404 })
          : new Response(JSON.stringify(fixture)),
      ),
    );
    vi.stubGlobal("fetch", fetch);
    const tree = createLeagueTree({ ...EXAMPLE_LEAGUE, path: "leagues/352490" });
    await expect(loadSuggestionHistory(tree, 101)).resolves.toEqual(fixture);
    expect(fetch).toHaveBeenCalledWith(
      "/data/leagues/352490/history/101.json",
      expect.objectContaining({ cache: "no-cache" }),
    );
  });
});

describe("requested history beside weekly publications", () => {
  const requested = (week = 5) => {
    const value = document();
    value.payload.weeks = [value.payload.weeks[0]];
    Object.assign(value.payload.weeks[0], {
      gameweek: week,
      advice_source: "requested_server",
      request_cache_key: "a".repeat(64),
    });
    return value;
  };
  const tree = (published: unknown, computed: unknown) => ({
    league: EXAMPLE_LEAGUE,
    raw: vi.fn(async (path: string) => {
      const value = path.includes("/requested/") ? computed : published;
      if (value instanceof Error) throw value;
      return value;
    }),
  });

  it("shows requested history when the entry never had a weekly publication", async () => {
    const value = requested();
    await expect(
      loadSuggestionHistory(tree(new LeagueDataMissing("legacy"), value), 101),
    ).resolves.toEqual(value);
  });

  it("adds new weeks and preserves every overlapping published week", async () => {
    const published = document();
    const computed = requested();
    computed.payload.weeks.push(requested(4).payload.weeks[0]);
    const loaded = await loadSuggestionHistory(tree(published, computed), 101);
    expect(loaded.payload.weeks.map((week) => week.gameweek)).toEqual([5, 4]);
    expect(loaded.payload.weeks.find((week) => week.gameweek === 4)).toEqual(
      published.payload.weeks[0],
    );
    expect(published).toEqual(document());
  });

  it("does not conceal malformed legacy evidence behind a requested result", async () => {
    await expect(
      loadSuggestionHistory(tree(new LeagueDataError("broken"), requested()), 101),
    ).rejects.toBeInstanceOf(LeagueDataError);
  });

  it("does not claim a weekly document as a requested answer", async () => {
    await expect(loadSuggestionHistory(tree(document(), document()), 101)).rejects.toBeInstanceOf(
      LeagueDataError,
    );
  });

  it("does not mix seasons", async () => {
    const value = requested();
    value.payload.season = "2025-26";
    await expect(loadSuggestionHistory(tree(document(), value), 101)).rejects.toBeInstanceOf(
      LeagueDataError,
    );
  });

  it.each([
    {},
    { advice_source: "requested_server" },
    { request_cache_key: "a".repeat(64) },
    { advice_source: "device", request_cache_key: "a".repeat(64) },
    { advice_source: "requested_server", request_cache_key: "bad" },
  ])("requires complete requested provenance: %o", async (fields) => {
    const value = document();
    Object.assign(value.payload.weeks[0], fields);
    await expect(
      loadSuggestionHistory(tree(new LeagueDataMissing("legacy"), value), 101),
    ).rejects.toBeInstanceOf(LeagueDataError);
  });

  it("forwards cancellation to both file reads", async () => {
    const input = tree(document(), new LeagueDataMissing("requested"));
    const options = { signal: new AbortController().signal };
    await loadSuggestionHistory(input, 101, options);
    expect(input.raw.mock.calls).toEqual([
      ["history/101.json", options],
      ["history/requested/101.json", options],
    ]);
  });
});
