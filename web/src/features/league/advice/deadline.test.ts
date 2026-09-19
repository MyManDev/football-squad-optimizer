import { describe, expect, it } from "vitest";

import { AS_A_CHANCE } from "../../../testSupport/honesty";
import type { FixturesPayload } from "../../fixtures/types";
import { COMPUTE_COPY } from "./computeCopy";
import { gameweekDeadline, passedDeadline } from "./deadline";

const CALENDAR: FixturesPayload = {
  season: "2026-27",
  source_snapshot_id: "fpl-live-test",
  captured_at_utc: "2026-09-18T12:25:16Z",
  current_gameweek: 5,
  unscheduled_count: 0,
  gameweeks: [
    { gameweek: 5, deadline_utc: "2026-09-18T17:30:00Z", fixtures: [] },
    { gameweek: 6, deadline_utc: "2026-10-10T10:00:00Z", fixtures: [] },
    { gameweek: 7, deadline_utc: "not a date", fixtures: [] },
  ],
};

describe("the deadline of the advised gameweek", () => {
  it("is read from the calendar of the same season", () => {
    expect(gameweekDeadline(CALENDAR, "2026-27", 5)).toBe("2026-09-18T17:30:00Z");
    expect(gameweekDeadline(CALENDAR, "2026-27", 6)).toBe("2026-10-10T10:00:00Z");
  });

  it("is unknown, never assumed, when the calendar does not say", () => {
    expect(gameweekDeadline(null, "2026-27", 5)).toBeNull();
    expect(gameweekDeadline(undefined, "2026-27", 5)).toBeNull();
    expect(gameweekDeadline(CALENDAR, "2025-26", 5)).toBeNull();
    expect(gameweekDeadline(CALENDAR, "2026-27", 8)).toBeNull();
    expect(gameweekDeadline(CALENDAR, "2026-27", 7)).toBeNull();
  });

  it("has passed from the stated instant on, and an unknown deadline never has", () => {
    const deadline = "2026-09-18T17:30:00Z";
    expect(passedDeadline(deadline, Date.parse("2026-09-18T17:29:59Z"))).toBeNull();
    expect(passedDeadline(deadline, Date.parse(deadline))).toBe(deadline);
    expect(passedDeadline(deadline, Date.parse("2026-09-19T08:00:00Z"))).toBe(deadline);
    expect(passedDeadline(null, Date.parse("2030-01-01T00:00:00Z"))).toBeNull();
  });

  it("is told to the member without any wording of chance", () => {
    for (const copy of Object.values(COMPUTE_COPY)) {
      for (const sentence of [
        copy.deadlinePassedTitle,
        copy.deadlinePassedBody(5, "18 Sep 2026, 20:30"),
        copy.deadlinePassedCompute,
      ]) {
        expect(sentence).not.toMatch(AS_A_CHANCE);
        expect(sentence).not.toContain(String.fromCharCode(0x2014));
      }
      expect(copy.deadlinePassedBody(5, "WHEN")).toContain("WHEN");
      expect(copy.deadlinePassedBody(5, "WHEN")).toContain("5");
    }
  });
});
