import { describe, expect, it } from "vitest";

import type { FixturesPayload } from "../fixtures/types";
import { liveWindow, MATCH_WINDOW_MS } from "./liveWindow";

const team = (team_id: number) => ({ team_id, name: `Club ${team_id}`, short_name: `C${team_id}` });
const fixture = (fixture_id: number, kickoff_utc: string | null) => ({
  fixture_id,
  kickoff_utc,
  home: team(1),
  away: team(2),
  finished: false,
  home_score: null,
  away_score: null,
});

const CALENDAR: FixturesPayload = {
  season: "2026-27",
  source_snapshot_id: "synthetic",
  captured_at_utc: "2026-11-20T00:00:00Z",
  current_gameweek: 11,
  unscheduled_count: 0,
  gameweeks: [
    {
      gameweek: 10,
      deadline_utc: "2026-11-07T11:00:00Z",
      fixtures: [fixture(91, "2026-11-07T15:00:00Z")],
    },
    {
      gameweek: 11,
      deadline_utc: "2026-11-21T11:00:00Z",
      fixtures: [
        fixture(101, "2026-11-21T12:30:00Z"),
        fixture(102, "2026-11-21T15:00:00Z"),
        fixture(103, null),
      ],
    },
    { gameweek: 12, deadline_utc: "2026-11-28T11:00:00Z", fixtures: [] },
  ],
};

const at = (iso: string) => Date.parse(iso);

describe("liveWindow", () => {
  it("is shut without a calendar", () => {
    expect(liveWindow(null, at("2026-11-21T13:00:00Z"))).toEqual({
      gameweek: null,
      open: false,
      changesIn: null,
    });
  });

  it("follows the latest week whose deadline has passed, shut until its first kickoff", () => {
    const window = liveWindow(CALENDAR, at("2026-11-21T11:30:00Z"));
    expect(window).toEqual({ gameweek: 11, open: false, changesIn: 60 * 60_000 });
  });

  it("opens at a kickoff and stays open for the match's window", () => {
    expect(liveWindow(CALENDAR, at("2026-11-21T12:30:00Z")).open).toBe(true);
    const late = liveWindow(CALENDAR, at("2026-11-21T14:40:00Z"));
    expect(late.open).toBe(true);
    expect(late.changesIn).toBe(5 * 60_000);
    const gap = liveWindow(CALENDAR, at("2026-11-21T14:46:00Z"));
    expect(gap).toMatchObject({ open: false, changesIn: 14 * 60_000 });
  });

  it("shuts after the last match's window and waits for the next deadline", () => {
    const after = at("2026-11-21T15:00:00Z") + MATCH_WINDOW_MS;
    const window = liveWindow(CALENDAR, after);
    expect(window.open).toBe(false);
    expect(window.changesIn).toBe(at("2026-11-28T11:00:00Z") - after);
  });

  it("is shut before the season's first deadline", () => {
    expect(liveWindow(CALENDAR, at("2026-11-01T00:00:00Z"))).toMatchObject({
      gameweek: null,
      open: false,
    });
  });
});
