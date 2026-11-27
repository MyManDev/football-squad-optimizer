import { describe, expect, it } from "vitest";
import type { Fixture, FixturesPayload } from "../features/fixtures/types";
import {
  availableWeek,
  openPlanWeek,
  weekState,
  WEEK_MATCH_LIMIT_MS,
  type WeekEvent,
} from "./weekState";

const at = Date.parse;
const deadline = at("2026-11-21T11:00:00Z");
const kickoff = at("2026-11-21T12:30:00Z");
const team = { team_id: 1, name: "Club", short_name: "CLB" };
const fixture = (id: number, time: number | null): Fixture => ({
  fixture_id: id,
  kickoff_utc: time === null ? null : new Date(time).toISOString(),
  home: team,
  away: { ...team, team_id: 2 },
  finished: false,
  home_score: null,
  away_score: null,
});
function calendar(fixtures = [fixture(1, kickoff)]): FixturesPayload {
  return {
    season: "2026-27",
    source_snapshot_id: "synthetic-week-policy",
    captured_at_utc: "2026-11-01T00:00:00Z",
    current_gameweek: 11,
    unscheduled_count: 0,
    gameweeks: [
      { gameweek: 10, deadline_utc: "2026-11-07T11:00:00Z", fixtures: [] },
      { gameweek: 11, deadline_utc: new Date(deadline).toISOString(), fixtures },
      {
        gameweek: 12,
        deadline_utc: "2026-11-28T11:00:00Z",
        fixtures: [fixture(2, kickoff + 7 * 86_400_000)],
      },
    ],
  };
}
const events: WeekEvent[] = [
  { gameweek: 10, finished: true, data_checked: true },
  { gameweek: 11, finished: false, data_checked: false },
];
function state(now: number, rows = events, fixtures = calendar(), treeGameweek = 11) {
  return weekState({ treeGameweek, events: rows, fixtures, now });
}

describe("the approved six-phase week policy", () => {
  it("preserves capture readers' exact microsecond plan boundary", () => {
    const deadlines = [
      { gameweek: 11, deadline: 2_000_000n },
      { gameweek: 10, deadline: 1_000_000n },
    ];
    expect(openPlanWeek(deadlines, 999_999n)).toBe(10);
    expect(openPlanWeek(deadlines, 1_000_000n)).toBe(11);
    expect(openPlanWeek(deadlines, 1_000_001n)).toBe(11);
    expect(openPlanWeek(deadlines, 2_000_000n)).toBeNull();
  });
  it.each([
    [deadline - 1_000, "before-deadline"],
    [deadline, "before-kickoff"],
    [deadline + 1_000, "before-kickoff"],
    [kickoff - 1_000, "before-kickoff"],
    [kickoff, "playing"],
    [kickoff + WEEK_MATCH_LIMIT_MS - 1_000, "playing"],
    [kickoff + WEEK_MATCH_LIMIT_MS, "played"],
    [kickoff + WEEK_MATCH_LIMIT_MS + 1_000, "played"],
  ])("at %s returns %s without moving the published plan", (now, phase) => {
    const value = state(Number(now));
    expect(value.phase).toBe(phase);
    expect(value.weeks.plan).toBe(11);
    expect(value.weeks.fixtures).toBe(phase === "played" ? 12 : 11);
  });

  it("pins N for scoreboard and last result while totals, race and history remain N-1 until checked", () => {
    const finished = [...events.slice(0, 1), { gameweek: 11, finished: true, data_checked: false }];
    const value = state(kickoff + 60_000, finished);
    expect(value.phase).toBe("finished");
    expect(value.weeks).toMatchObject({
      scoreboard: 11,
      lastResult: 11,
      leagueTotal: 10,
      race: 10,
      history: 10,
    });
    const checked = state(
      kickoff + 60_000,
      finished.map((row) => ({ ...row, data_checked: true })),
    );
    expect(checked.phase).toBe("checked");
    expect(checked.weeks).toMatchObject({
      scoreboard: 11,
      lastResult: 11,
      leagueTotal: 11,
      race: 11,
      history: 11,
    });
    expect(value.weeks.live).toBeNull();
  });

  it("keeps every consumer's current week when its phase target has no data row", () => {
    const input = state(kickoff);
    const current = Object.fromEntries(Object.keys(input.targets).map((key) => [key, 9]));
    const available = Object.fromEntries(Object.keys(input.targets).map((key) => [key, [9]]));
    const kept = weekState({
      treeGameweek: 11,
      events,
      fixtures: calendar(),
      now: kickoff,
      current,
      available,
    });
    expect(Object.values(kept.weeks)).toEqual(
      Object.values(input.targets).map((target) => (target === null ? null : 9)),
    );
    expect(availableWeek(11, 10, [10, 11])).toBe(11);
    expect(availableWeek(11, 10, [10])).toBe(10);
  });

  it("rolls the closed rail with fixtures, without opening the plan or assigning Q its resources", () => {
    const value = state(kickoff + WEEK_MATCH_LIMIT_MS);
    expect(value.weeks).toMatchObject({
      plan: 11,
      topBar: 11,
      resources: null,
      memberRail: 12,
      fixtures: 12,
      memberScore: 11,
      liveWaiting: 12,
    });
    expect(value.planClosed).toBe(true);
  });

  it("moves from checked N to pre-deadline Q only when its new tree arrives", () => {
    const checked = events.map((row) => ({ ...row, finished: true, data_checked: true }));
    const now = kickoff + 86_400_000;
    expect(state(now, checked).phase).toBe("checked");
    expect(state(now, checked, calendar(), 12)).toMatchObject({
      phase: "before-deadline",
      gameweek: 12,
      planClosed: false,
    });
  });

  it("lets the next elapsed deadline take precedence even when the old tree or flags lag", () => {
    const next = at("2026-11-28T11:00:00Z");
    expect(state(next)).toMatchObject({ gameweek: 12, elapsedGameweek: 12, planClosed: true });
    expect(state(next).weeks.plan).toBe(11);
  });

  it("preserves N between the matches of a double week and uses its final 180-minute boundary", () => {
    const later = kickoff + 86_400_000;
    const double = calendar([fixture(1, kickoff), fixture(2, later)]);
    expect(state(kickoff + WEEK_MATCH_LIMIT_MS, events, double).phase).toBe("playing");
    expect(state(later + WEEK_MATCH_LIMIT_MS - 1_000, events, double).weeks.fixtures).toBe(11);
    expect(state(later + WEEK_MATCH_LIMIT_MS, events, double).weeks.fixtures).toBe(12);
  });

  it("does not confuse a listed blank week with missing calendar data", () => {
    expect(state(deadline, events, calendar([])).phase).toBe("played");
    const missing = weekState({ treeGameweek: 11, events, fixtures: null, now: deadline });
    expect(missing).toMatchObject({ phase: "unavailable", gameweek: null, planClosed: null });
    expect(missing.weeks.plan).toBe(11);
    expect(missing.weeks.resources).toBe(11);
    expect(missing.weeks.memberRail).toBe(11);
    expect(missing.weeks.scoreboard).toBeNull();
  });

  it("retains undated unfinished fixtures until flags or a revised calendar resolve them", () => {
    expect(state(deadline, events, calendar([fixture(1, null)])).phase).toBe("before-kickoff");
    expect(
      state(
        kickoff + WEEK_MATCH_LIMIT_MS,
        events,
        calendar([fixture(1, kickoff), fixture(2, null)]),
      ).phase,
    ).toBe("playing");
    const revised = calendar([fixture(1, kickoff + 86_400_000)]);
    expect(state(kickoff + WEEK_MATCH_LIMIT_MS, events, revised).phase).toBe("before-kickoff");
  });

  it.each([-1_000, 0, 1_000])(
    "keeps an undated match on N but bounds LIVE at the last known kickoff +180 minutes (%s ms)",
    (offset) => {
      const end = kickoff + WEEK_MATCH_LIMIT_MS;
      const undated = calendar([fixture(1, kickoff), fixture(2, null)]);
      const value = state(end + offset, events, undated);
      expect(value.phase).toBe("playing");
      expect(value.weeks.fixtures).toBe(11);
      expect(value.weeks.memberRail).toBe(11);
      expect(value.weeks.live).toBe(offset < 0 ? 11 : null);
      expect(value.weeks.pill).toBe(offset < 0 ? 11 : null);
      expect(value.weeks.liveWaiting).toBe(offset < 0 ? null : 12);
      if (offset < 0) expect(value.changesIn).toBe(1_000);
    },
  );

  it("honors flag and next-deadline transitions after the undated-match LIVE limit", () => {
    const undated = calendar([fixture(1, kickoff), fixture(2, null)]);
    const now = kickoff + WEEK_MATCH_LIMIT_MS;
    expect(
      state(
        now,
        events.map((row) => ({ ...row, finished: true })),
        undated,
      ).phase,
    ).toBe("finished");
    expect(
      state(
        now,
        events.map((row) => ({ ...row, finished: true, data_checked: true })),
        undated,
      ).phase,
    ).toBe("checked");
    expect(state(at("2026-11-28T11:00:00Z"), events, undated).gameweek).toBe(12);
  });

  it("accepts authoritative fixture completion before the time limit", () => {
    const done = calendar([{ ...fixture(1, kickoff), finished: true }]);
    expect(state(kickoff + 60_000, events, done).phase).toBe("played");
  });

  it("ignores flags before a deadline and never treats checked alone as finished", () => {
    const flags = events.map((row) => ({ ...row, data_checked: true }));
    expect(state(deadline - 1_000, flags).phase).toBe("before-deadline");
    expect(state(kickoff, flags).phase).toBe("playing");
    expect(state(kickoff, flags).weeks.history).toBe(10);
  });

  it("does not roll backward behind capture time and reports the next exact clock boundary", () => {
    const captured = { ...calendar(), captured_at_utc: new Date(kickoff).toISOString() };
    expect(state(deadline - 1_000, events, captured)).toMatchObject({
      phase: "playing",
      clock: kickoff,
      changesIn: WEEK_MATCH_LIMIT_MS,
    });
    expect(state(deadline - 1_000).changesIn).toBe(1_000);
  });

  it("does not invent the next week at season end or assume consecutive calendar numbers", () => {
    const last = calendar();
    last.gameweeks = last.gameweeks.slice(0, 2);
    expect(state(kickoff + WEEK_MATCH_LIMIT_MS, events, last).weeks.fixtures).toBeNull();
    const gap = calendar();
    gap.gameweeks[2]!.gameweek = 14;
    expect(state(kickoff + WEEK_MATCH_LIMIT_MS, events, gap).weeks.fixtures).toBe(14);
  });
});
