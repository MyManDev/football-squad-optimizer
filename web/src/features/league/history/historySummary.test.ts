import { expect, it } from "vitest";
import { mockSuggestionOverview } from "../../../fixtures/weeklySuggestionOverview";
import { checkedHistory } from "./historyData";
import { settledHistoryWeeks, summarizeHistory } from "./historySummary";

it("keeps C when the next recorded week is unsettled, and keeps the comparison endpoint without its actual row", () => {
  const old = mockSuggestionOverview().payload.weeks[0]!;
  const base = summarizeHistory([old]);
  const next = {
    ...structuredClone(old),
    gameweek: old.gameweek + 1,
    status: "unsettled" as const,
  };
  const pending = summarizeHistory([old, next]);
  expect(pending).toMatchObject({
    throughGameweek: old.gameweek,
    suggested: base.suggested,
    actual: base.actual,
    difference: base.difference,
  });
  const partial = {
    ...next,
    status: "available" as const,
    actual: null,
    actual_reason: "not_available",
    net_difference: null,
  };
  expect(settledHistoryWeeks([old, partial])).toEqual([old.gameweek, next.gameweek]);
  expect(summarizeHistory([old, partial])).toMatchObject({
    throughGameweek: old.gameweek,
    suggested: base.suggested,
    actual: base.actual,
    difference: base.difference,
  });
  expect(summarizeHistory([old, { ...next, status: "available" as const }]).throughGameweek).toBe(
    next.gameweek,
  );
});

it("sums the same final weeks on both sides and keeps chronological running differences", () => {
  const history = checkedHistory(mockSuggestionOverview(), 101);
  const before = structuredClone(history);
  const summary = summarizeHistory([...history.payload.weeks].reverse());
  expect(summary.rows.map((row) => row.week.gameweek)).toEqual([
    4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14,
  ]);
  expect(summary.rows.map((row) => row.cumulative)).toEqual([
    -2,
    4,
    8,
    12,
    9,
    17,
    17,
    12,
    null,
    14,
    null,
  ]);
  expect(summary).toMatchObject({ suggested: 624, actual: 610, difference: 14 });
  expect(history).toEqual(before);
});

it("does not turn an empty or unfinished history into zero totals", () => {
  expect(summarizeHistory([])).toMatchObject({
    suggested: null,
    actual: null,
    difference: null,
  });
  expect(summarizeHistory(mockSuggestionOverview().payload.weeks.slice(-1))).toMatchObject({
    suggested: null,
    actual: null,
    difference: null,
  });
});

it("adds a newly published week once, even when the view is re-rendered", () => {
  const weeks = mockSuggestionOverview().payload.weeks.slice(0, 4);
  expect(summarizeHistory(weeks.slice(0, 3))).toMatchObject({ difference: 8 });
  expect(summarizeHistory(weeks)).toMatchObject({
    suggested: 152,
    actual: 140,
    difference: 12,
  });
  expect(summarizeHistory(weeks).difference).toBe(12);
});
