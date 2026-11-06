import { describe, expect, it } from "vitest";

import {
  exampleCalendar,
  exampleMember,
  exampleTable,
  forwardedLive,
  LIVE_EXAMPLES,
  type LiveExample,
} from "../../../fixtures/forwarder";
import { scoreMemberWeek } from "../../liveScore/officialScoring";
import { memberLiveScore } from "./memberLiveScore";

const SEASON = "2026-27";
const inputs = (name: LiveExample) => ({
  live: forwardedLive(name, 6),
  member: exampleMember(101, 6),
  table: exampleTable({ season: SEASON, gameweek: 7, capture: "synthetic-capture" }),
  fixtures: exampleCalendar({ season: SEASON, gameweek: 6, deadline: "2026-10-10T10:00:00Z" }),
});

describe("the member's live week from the forwarder and the capture's table", () => {
  it.each(["in_progress", "finished"] as const)(
    "scores the %s example as the contract's own resolved form scores",
    (name) => {
      const result = memberLiveScore(inputs(name));
      if (!result.ok) throw new Error(result.reason);
      const { members, ...example } = LIVE_EXAMPLES[name];
      expect(result.live.score).toEqual(scoreMemberWeek(example, members![0]));
      expect(result.live.gameweek).toBe(6);
      expect(result.live.score.bonus_confirmed).toBe(name === "finished");
      expect(result.live.names.get(7)).toBe("Player 7");
      expect(result.live.names.size).toBe(15);
    },
  );

  it("refuses a member week of another gameweek", () => {
    expect(memberLiveScore({ ...inputs("in_progress"), member: exampleMember(101, 5) })).toEqual({
      ok: false,
      reason: "other_week",
    });
  });

  it("refuses a table or a calendar of another season", () => {
    const base = inputs("in_progress");
    expect(memberLiveScore({ ...base, table: { ...base.table, season: "2025-26" } })).toEqual({
      ok: false,
      reason: "other_season",
    });
    expect(memberLiveScore({ ...base, fixtures: { ...base.fixtures, season: "2025-26" } })).toEqual(
      { ok: false, reason: "other_season" },
    );
  });

  it("refuses the tree's copy of the table, which names no element ids", () => {
    const base = inputs("finished");
    const copy = { ...base.table, contract_version: "league_device_plan_v1" as const };
    expect(memberLiveScore({ ...base, table: copy })).toEqual({
      ok: false,
      reason: "table_without_element_ids",
    });
  });

  it("refuses a pick the table does not name", () => {
    const base = inputs("finished");
    const table = {
      ...base.table,
      players: base.table.players.filter((player) => player.element_id !== 12),
    };
    expect(memberLiveScore({ ...base, table })).toEqual({
      ok: false,
      reason: "pick_not_in_table",
    });
  });

  it("refuses a pick whose club the calendar does not name", () => {
    const base = inputs("finished");
    const fixtures = {
      ...base.fixtures,
      gameweeks: base.fixtures.gameweeks.map((week) => ({
        ...week,
        fixtures: week.fixtures.slice(1),
      })),
    };
    expect(memberLiveScore({ ...base, fixtures })).toEqual({
      ok: false,
      reason: "club_not_in_calendar",
    });
  });

  it("passes the scorer's refusal on, for a pick the live week does not carry", () => {
    const base = inputs("finished");
    const live = {
      ...base.live,
      elements: base.live.elements.filter((row) => row.element_id !== 3),
    };
    expect(memberLiveScore({ ...base, live })).toEqual({
      ok: false,
      reason: "score_refused",
      detail: "missing_pick",
    });
  });
});
