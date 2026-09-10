import { expect, it } from "vitest";
import { mockSuggestionOverview } from "../../../fixtures/weeklySuggestionOverview";
import { checkedHistory } from "./historyData";
import { summarizeHistory } from "./historySummary";

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
  expect(summary).toMatchObject({ compared: 9, suggested: 624, actual: 610, difference: 14 });
  expect(history).toEqual(before);
});

it("does not turn an empty or unfinished history into zero totals", () => {
  expect(summarizeHistory([])).toMatchObject({
    compared: 0,
    suggested: null,
    actual: null,
    difference: null,
  });
  expect(summarizeHistory(mockSuggestionOverview().payload.weeks.slice(-1))).toMatchObject({
    compared: 0,
    suggested: null,
    actual: null,
    difference: null,
  });
});

it("adds a newly published week once, even when the view is re-rendered", () => {
  const weeks = mockSuggestionOverview().payload.weeks.slice(0, 4);
  expect(summarizeHistory(weeks.slice(0, 3))).toMatchObject({ compared: 3, difference: 8 });
  expect(summarizeHistory(weeks)).toMatchObject({
    compared: 4,
    suggested: 152,
    actual: 140,
    difference: 12,
  });
  expect(summarizeHistory(weeks).difference).toBe(12);
});
