import { describe, expect, it } from "vitest";

import type { FixturesPayload } from "../fixtures/types";
import { liveWindow, MATCH_WINDOW_LIMIT_MS, MATCH_WINDOW_MS } from "./liveWindow";

const team = (team_id: number) => ({ team_id, name: `Club ${team_id}`, short_name: `C${team_id}` });
const fixture = (fixture_id: number, kickoff_utc: string | null, home = 1, away = 2) => ({
  fixture_id,
  kickoff_utc,
  home: team(home),
  away: team(away),
  finished: false,
  home_score: null,
  away_score: null,
});

const CALENDAR: FixturesPayload = {
  season: "2026-27",
  source_snapshot_id: "synthetic",
  captured_at_utc: "2026-10-30T00:00:00Z",
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
      slow: false,
      changesIn: null,
    });
  });

  it("follows the latest week whose deadline has passed, shut until its first kickoff", () => {
    const window = liveWindow(CALENDAR, at("2026-11-21T11:30:00Z"));
    expect(window).toEqual({ gameweek: 11, open: false, slow: false, changesIn: 60 * 60_000 });
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

  it("never reads the calendar earlier than its capture", () => {
    const captured = { ...CALENDAR, captured_at_utc: "2026-11-21T12:45:00Z" };
    // A device clock a week behind still sees the week the calendar was captured in.
    expect(liveWindow(captured, at("2026-11-14T12:45:00Z"))).toMatchObject({
      gameweek: 11,
      open: true,
    });
  });

  it("counts only the member's clubs' matches when they are given", () => {
    const calendar: FixturesPayload = {
      ...CALENDAR,
      gameweeks: [
        {
          gameweek: 11,
          deadline_utc: "2026-11-21T11:00:00Z",
          fixtures: [
            fixture(101, "2026-11-21T12:30:00Z", 1, 2),
            fixture(102, "2026-11-21T17:30:00Z", 3, 4),
          ],
        },
      ],
    };
    const now = at("2026-11-21T13:00:00Z");
    expect(liveWindow(calendar, now).open).toBe(true);
    const mine = liveWindow(calendar, now, { clubs: new Set([4, 9]) });
    expect(mine).toMatchObject({ open: false, changesIn: at("2026-11-21T17:30:00Z") - now });
    expect(liveWindow(calendar, at("2026-11-21T17:45:00Z"), { clubs: new Set([4]) }).open).toBe(
      true,
    );
  });

  it("stays open past the usual window while the live read names the match unfinished", () => {
    const late = at("2026-11-21T15:00:00Z") + MATCH_WINDOW_MS + 10 * 60_000;
    expect(liveWindow(CALENDAR, late).open).toBe(false);
    const unfinished = liveWindow(CALENDAR, late, { unfinished: new Set([102]) });
    expect(unfinished.open).toBe(true);
    const limit = at("2026-11-21T15:00:00Z") + MATCH_WINDOW_LIMIT_MS;
    expect(liveWindow(CALENDAR, limit, { unfinished: new Set([102]) }).open).toBe(false);
  });

  it("reads now and then, until the limit, a match whose minutes stood still past its window", () => {
    const late = at("2026-11-21T15:00:00Z") + MATCH_WINDOW_MS + 10 * 60_000;
    const stalled = liveWindow(CALENDAR, late, { stalled: new Set([102]) });
    expect(stalled).toMatchObject({ gameweek: 11, open: false, slow: true });
    // Its limit is the next change.
    expect(stalled.changesIn).toBe(MATCH_WINDOW_LIMIT_MS - MATCH_WINDOW_MS - 10 * 60_000);
    const limit = at("2026-11-21T15:00:00Z") + MATCH_WINDOW_LIMIT_MS;
    expect(liveWindow(CALENDAR, limit, { stalled: new Set([102]) }).slow).toBe(false);
    // Another club's stalled match, or one still within its window, reads at the usual pace.
    const others = liveWindow(CALENDAR, late, { clubs: new Set([7]), stalled: new Set([102]) });
    expect(others.slow).toBe(false);
    const inside = liveWindow(CALENDAR, at("2026-11-21T15:30:00Z"), { stalled: new Set([102]) });
    expect(inside).toMatchObject({ open: true, slow: false });
  });
});
