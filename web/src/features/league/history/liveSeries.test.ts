import { afterEach, describe, expect, it, vi } from "vitest";
import { mockSuggestionOverview } from "../../../fixtures/weeklySuggestionOverview";
import type { Scoreboard } from "../types";
import {
  loadLiveSeries,
  remainingWeeks,
  SERIES_BASIS,
  SERIES_POPULATION,
  summarizeLiveSeries,
} from "./liveSeries";

const history = mockSuggestionOverview();
const view: Scoreboard = {
  season: history.payload.season,
  league_id: 352490,
  source_snapshot_id: history.payload.as_of_snapshot_id,
  captured_at_utc: history.generated_at_utc,
  cohort_snapshot_id: null,
  cohort_picks_snapshot_id: null,
  registered_members: 2,
  histories_held: 2,
  gameweeks: history.payload.weeks.map((week) => ({
    gameweek: week.gameweek,
    deadline_utc: week.deadline_utc ?? "",
    finished: week.status !== "unsettled",
    data_checked: week.status !== "unsettled",
    average_entry_score: null,
    highest_score: null,
    ours: null,
    top100: null,
    members: [101, 202].map((entry_id) => ({
      entry_id,
      points: 0,
      net: 0,
      hit_cost: 0,
      total_points: 0,
    })),
    members_mean_net: null,
    members_counted: 2,
  })),
  cumulative: {
    through_gameweek: null,
    gameweeks: [],
    ours_net: null,
    ours_gameweeks: [],
    members_mean_total_points: null,
    members_gameweeks: [],
    members_counted: 0,
    average_entry_score: null,
  },
};
afterEach(() => vi.unstubAllGlobals());

describe("member-week series", () => {
  it("keeps members in weekly groups and excludes incomplete pairs", () => {
    const other = structuredClone(history);
    other.payload.entry_id = 202;
    const series = summarizeLiveSeries([history, other], view);
    expect(series.memberWeeks).toBe(18);
    expect(series.weekClusters).toBe(9);
    expect(series.weeks.every((week) => week.members === 2)).toBe(true);
    expect(series.meanDifference).toBeCloseTo(14 / 9);
    expect(new Set(series.rows.map((row) => row.recordKey)).size).toBe(18);
  });
  it("never turns an empty record into a zero result", () => {
    expect(summarizeLiveSeries([], view)).toMatchObject({
      memberWeeks: 0,
      weekClusters: 0,
      meanDifference: null,
    });
  });
  it("excludes an unchecked week even if the history has a score", () => {
    const unchecked = structuredClone(view);
    unchecked.gameweeks[0].data_checked = false;
    expect(summarizeLiveSeries([history], unchecked).memberWeeks).toBe(8);
  });
  it.each(["season", "capture", "duplicate"])("refuses mixed series: %s", (mismatch) => {
    const changed = structuredClone(history);
    if (mismatch === "season") changed.payload.season = "2025-26";
    if (mismatch === "capture") changed.payload.as_of_snapshot_id = "other";
    expect(() =>
      summarizeLiveSeries(mismatch === "duplicate" ? [history, history] : [changed], view),
    ).toThrow();
  });
  it("reads the measured week target only for exactly the measured records", () => {
    const series = summarizeLiveSeries([history], view);
    const measurement = {
      contract_version: "member_week_horizon_v1",
      season: view.season,
      league_id: 352490,
      scoring_basis: SERIES_BASIS,
      population: SERIES_POPULATION,
      measurement_artifact: "docs/member_week_measurement.json",
      within_week_correlation: 0.3,
      required_week_clusters: 20,
      member_week_keys: series.rows.map((row) => row.recordKey),
    };
    expect(remainingWeeks(measurement, series, view)).toBe(11);
    expect(remainingWeeks({ ...measurement, required_week_clusters: 9 }, series, view)).toBe(0);
    for (const invalid of [
      null,
      {},
      { ...measurement, within_week_correlation: null },
      { ...measurement, scoring_basis: "named_eleven_no_autosubs" },
      { ...measurement, member_week_keys: measurement.member_week_keys.slice(1) },
      { ...measurement, required_week_clusters: 2.5 },
    ]) {
      expect(remainingWeeks(invalid, series, view)).toBeNull();
    }
    const one = summarizeLiveSeries([history], { ...view, gameweeks: view.gameweeks.slice(0, 1) });
    expect(
      remainingWeeks(
        { ...measurement, member_week_keys: one.rows.map((row) => row.recordKey) },
        one,
        view,
      ),
    ).toBeNull();
  });
  it("loads real history files and reports a missing member without inventing rows", async () => {
    const fetcher = vi.fn(
      async (url: string) =>
        new Response(url.endsWith("/101.json") ? JSON.stringify(history) : "", {
          status: url.endsWith("/101.json") ? 200 : 404,
        }),
    );
    vi.stubGlobal("fetch", fetcher);
    const result = await loadLiveSeries(view);
    expect(result).toMatchObject({
      unavailableMembers: 1,
      remaining: null,
      series: { memberWeeks: 9, weekClusters: 9 },
    });
    expect(fetcher.mock.calls.map(([url]) => url)).toContain("/data/league/series-horizon.json");
  });
});
