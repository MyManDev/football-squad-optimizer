import { expect, it } from "vitest";
import { memberWeekPolicy } from "./memberWeekPolicy";

it("keeps published targets when the calendar is missing instead of treating it as season end", () => {
  const published = { gameweek: 11, season: "2026-27", league_id: 1 };
  const state = memberWeekPolicy(published, null, null, Date.parse("2026-11-27T12:00:00Z"));
  expect(state.phase).toBe("unavailable");
  expect(state.planClosed).toBeNull();
  expect(state.weeks).toMatchObject({ plan: 11, topBar: 11, resources: 11, memberRail: 11 });
});

it("does not close a published plan against another season's calendar", () => {
  const state = memberWeekPolicy(
    { gameweek: 11, season: "2026-27", league_id: 1 },
    {
      season: "2024-25",
      source_snapshot_id: "synthetic-other-season",
      captured_at_utc: "2024-11-01T00:00:00Z",
      current_gameweek: 11,
      unscheduled_count: 0,
      gameweeks: [{ gameweek: 11, deadline_utc: "2024-11-21T11:00:00Z", fixtures: [] }],
    },
    null,
    Date.parse("2026-11-27T12:00:00Z"),
  );
  expect(state.planClosed).toBeNull();
  expect(state.weeks.plan).toBe(11);
  expect(state.weeks.resources).toBe(11);
});
