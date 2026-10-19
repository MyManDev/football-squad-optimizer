import { describe, expect, it } from "vitest";

import type { Fixture, FixturesPayload } from "../../../fixtures/types";
import type { ChipWindowState, EntrySquad, EntrySquadPlayer } from "../../types";
import {
  calendarCounts,
  forecastSource,
  heldChips,
  memberChipForecast,
  type ForecastSource,
  type MemberChipForecastInputs,
} from "./member";

const CAPTURE = "fpl-live-20261002T104314Z-8b70515b9b31";
const CLUBS = ["Alpha", "Beta", "Gamma", "Delta"];

function fixture(id: number, home: number, away: number): Fixture {
  const team = (club: number) => ({
    team_id: club,
    name: CLUBS[club - 1]!,
    short_name: CLUBS[club - 1]!.slice(0, 3).toUpperCase(),
  });
  return {
    fixture_id: id,
    kickoff_utc: null,
    home: team(home),
    away: team(away),
    finished: false,
    home_score: null,
    away_score: null,
  };
}

/** Every club once a week, gameweeks 1 to 38: a calendar with no structure. */
function calendar(): FixturesPayload {
  return {
    season: "2026-27",
    source_snapshot_id: CAPTURE,
    captured_at_utc: "2026-10-02T10:43:14Z",
    current_gameweek: 7,
    unscheduled_count: 0,
    gameweeks: Array.from({ length: 38 }, (_, index) => ({
      gameweek: index + 1,
      deadline_utc: "2026-10-03T10:00:00Z",
      fixtures: [fixture((index + 1) * 10 + 1, 1, 2), fixture((index + 1) * 10 + 2, 3, 4)],
    })),
  };
}

function window(state: ChipWindowState["state"], start: number, stop: number): ChipWindowState {
  return { state, gameweek: state === "used" ? start : null, start_event: start, stop_event: stop };
}

/** Fifteen players, ids 101 to 115, over the four clubs; 101 is the captain. */
function inputs(): MemberChipForecastInputs {
  const ids = Array.from({ length: 15 }, (_, index) => 101 + index);
  const player = (id: number) =>
    ({ player_id: id, is_captain: id === 101 }) as unknown as EntrySquadPlayer;
  const squad = {
    league_id: 352490,
    season: "2026-27",
    gameweek: 7,
    entry: { member_kind: "human", entry_id: 7252721 },
    starting_xi: ids.slice(0, 11).map(player),
    bench: ids.slice(11).map(player),
    source_snapshot_id: CAPTURE,
    chips: {
      known: true,
      gameweek: 7,
      states: {
        wildcard: {
          first_half: window("available", 2, 19),
          second_half: window("not_yet", 20, 38),
        },
        freehit: { first_half: window("available", 2, 19), second_half: window("not_yet", 20, 38) },
        bboost: { first_half: window("available", 1, 19), second_half: window("not_yet", 20, 38) },
        "3xc": { first_half: window("available", 1, 19), second_half: window("not_yet", 20, 38) },
      },
    },
  } as unknown as EntrySquad;
  return {
    table: {
      season: "2026-27",
      gameweek: 7,
      source_snapshot_id: CAPTURE,
      players: [...ids, 116].map((id, index) => ({
        id,
        team: CLUBS[index % 4]!,
        position: index === 0 || index === 11 ? "GK" : index < 6 ? "DEF" : "MID",
        expected_points: 2 + index * 0.25,
      })),
    },
    squad,
    fixtures: calendar(),
    gains: {},
  };
}

function source(payload: FixturesPayload): ForecastSource {
  return forecastSource(payload)!;
}

describe("the calendar counts", () => {
  it("state every club each week, a blank as an explicit zero and a double as two", () => {
    const payload = calendar();
    // Gameweek 10: Gamma and Delta blank. Gameweek 12: Alpha and Gamma play twice.
    payload.gameweeks[9]!.fixtures = [fixture(101, 1, 2)];
    payload.gameweeks[11]!.fixtures.push(fixture(999, 1, 3));
    const weeks = calendarCounts(source(payload), { first: 9, last: 12 });
    expect(weeks.map((week) => week.gameweek)).toEqual([9, 10, 11, 12]);
    expect(weeks[0]!.fixture_count_by_club).toEqual({ 1: 1, 2: 1, 3: 1, 4: 1 });
    expect(weeks[1]!.fixture_count_by_club).toEqual({ 1: 1, 2: 1, 3: 0, 4: 0 });
    expect(weeks[3]!.fixture_count_by_club).toEqual({ 1: 2, 2: 1, 3: 2, 4: 1 });
  });

  it("keep a club with no fixture all season out of no week: the roster is the calendar's", () => {
    const payload = calendar();
    // A week where nobody plays is still a week of four explicit zeros.
    payload.gameweeks[14]!.fixtures = [];
    expect(
      calendarCounts(source(payload), { first: 15, last: 15 })[0]!.fixture_count_by_club,
    ).toEqual({ 1: 0, 2: 0, 3: 0, 4: 0 });
  });

  it("refuse a calendar with unscheduled fixtures", () => {
    const payload = { ...calendar(), unscheduled_count: 1 };
    expect(() => calendarCounts(source(payload), { first: 7, last: 19 })).toThrow(
      "fixtures_unscheduled",
    );
  });

  it("refuse a calendar that names no club", () => {
    const payload = calendar();
    for (const week of payload.gameweeks) week.fixtures = [];
    expect(() => calendarCounts(source(payload), { first: 7, last: 19 })).toThrow(
      "club_roster_missing",
    );
  });

  it("refuse a missing week, a repeated week and a repeated fixture inside the range only", () => {
    const missing = calendar();
    missing.gameweeks.splice(14, 1);
    expect(() => calendarCounts(source(missing), { first: 7, last: 19 })).toThrow(
      "calendar_incomplete",
    );
    expect(calendarCounts(source(missing), { first: 7, last: 14 })).toHaveLength(8);
    const repeated = calendar();
    repeated.gameweeks.push(repeated.gameweeks[30]!);
    expect(() => calendarCounts(source(repeated), { first: 7, last: 19 })).toThrow(
      "calendar_incomplete",
    );
    const twice = calendar();
    twice.gameweeks[8]!.fixtures.push(twice.gameweeks[8]!.fixtures[0]!);
    expect(() => calendarCounts(source(twice), { first: 7, last: 19 })).toThrow(
      "calendar_incomplete",
    );
    expect(calendarCounts(source(twice), { first: 10, last: 19 })).toHaveLength(10);
  });
});

describe("the member's reading", () => {
  it("binds the rule to the table, the entry and the calendar", () => {
    const reading = memberChipForecast({ ...inputs(), gains: { wildcard: 9, bboost: 0 } });
    expect(reading).toMatchObject({
      season: "2026-27",
      league_id: 352490,
      entry_id: 7252721,
      gameweek: 7,
      source_snapshot_id: CAPTURE,
      squad_player_ids: Array.from({ length: 15 }, (_, index) => 101 + index),
      bench_player_ids: [112, 113, 114, 115],
      status: "available",
      reason: null,
      calendar_has_structure: false,
      calendar_range: { first_gameweek: 8, last_gameweek: 19 },
    });
    const chips = reading.forecast!.chips;
    expect(chips.map((chip) => [chip.name, chip.verdict])).toEqual([
      ["wildcard", "play_now"],
      ["freehit", "unknown_this_week"],
      ["bboost", "hold"],
      ["3xc", "unknown_this_week"],
    ]);
    // The bench is the four after the eleven, in the entry's order.
    expect(chips[2]!.points_at_gameweek).toMatchObject({
      gameweek: 8,
      estimated_gain: 20.5,
      player_ids: [112, 113, 114, 115],
    });
    expect(reading.forecast!.players_without_fixture_this_week).toEqual([]);
  });

  it("reads an absent gain as unknown, never as zero", () => {
    const unknown = memberChipForecast(inputs()).forecast!.chips.find((c) => c.name === "bboost")!;
    expect(unknown.verdict).toBe("unknown_this_week");
    expect(unknown.gain_this_week).toBeNull();
    const zero = memberChipForecast({ ...inputs(), gains: { bboost: 0 } }).forecast!.chips.find(
      (c) => c.name === "bboost",
    )!;
    expect(zero.verdict).toBe("hold");
    expect(zero.gain_this_week).toBe(0);
  });

  it("states a structured calendar and a player whose club blanks this week", () => {
    const base = inputs();
    const payload = calendar();
    payload.gameweeks[6]!.fixtures = [fixture(71, 1, 2)];
    payload.gameweeks[11]!.fixtures.push(fixture(999, 1, 3));
    const blankClubs = new Set(["Gamma", "Delta"]);
    const table = {
      ...base.table,
      players: base.table.players.map((player) =>
        blankClubs.has(player.team) ? { ...player, expected_points: 0 } : player,
      ),
    };
    const reading = memberChipForecast({ ...base, table, fixtures: payload });
    expect(reading.status).toBe("available");
    expect(reading.calendar_has_structure).toBe(true);
    expect(reading.forecast!.players_without_fixture_this_week).toEqual([
      103, 104, 107, 108, 111, 112, 115,
    ]);
  });

  it("states a later blank alone as structure, and a blank after every held window as none", () => {
    const later = inputs();
    later.fixtures!.gameweeks[9]!.fixtures = [fixture(101, 1, 2)];
    expect(memberChipForecast(later).calendar_has_structure).toBe(true);
    const after = inputs();
    after.fixtures!.gameweeks[24]!.fixtures = [fixture(251, 1, 2)];
    expect(memberChipForecast(after).calendar_has_structure).toBe(false);
  });

  it("holds no chip with only this week's calendar read", () => {
    const base = inputs();
    for (const halves of Object.values(base.squad.chips!.states)) {
      halves.first_half = window("used", halves.first_half!.start_event, 19);
    }
    expect(heldChips(base.squad.chips, 7)).toEqual([]);
    const reading = memberChipForecast(base);
    expect(reading.status).toBe("available");
    expect(reading.forecast!.chips).toEqual([]);
    expect(reading.calendar_has_structure).toBe(false);
    expect(reading.calendar_range).toBeNull();
  });

  it("names the held chips in the game's order, and none where the history is unknown", () => {
    const base = inputs();
    expect(heldChips(base.squad.chips, 7)).toEqual(["wildcard", "freehit", "bboost", "3xc"]);
    expect(heldChips(base.squad.chips, 1)).toEqual(["bboost", "3xc"]);
    expect(heldChips(undefined, 7)).toBeNull();
    expect(heldChips({ ...base.squad.chips!, known: false }, 7)).toBeNull();
  });
});

describe("the member's reading is refused with the publisher's code", () => {
  const refused = (
    change: (value: MemberChipForecastInputs) => MemberChipForecastInputs | void,
  ) => {
    const base = inputs();
    const reading = memberChipForecast(change(base) ?? base);
    expect(reading).toMatchObject({
      status: "unavailable",
      forecast: null,
      calendar_has_structure: null,
      calendar_range: null,
    });
    return reading.reason;
  };

  it.each<[string, (value: MemberChipForecastInputs) => void]>([
    ["the calendar's capture", (v) => void (v.fixtures!.source_snapshot_id = "another")],
    ["the entry's capture", (v) => void (v.squad.source_snapshot_id = "another")],
    ["the entry without a capture", (v) => void (v.squad.source_snapshot_id = null)],
    ["the entry's season", (v) => void (v.squad.season = "2025-26")],
    ["the calendar's season", (v) => void (v.fixtures!.season = "2025-26")],
    ["the entry's gameweek", (v) => void (v.squad.gameweek = 6)],
    ["the chip windows' gameweek", (v) => void (v.squad.chips!.gameweek = 6)],
  ])("capture_mismatch: %s differs", (_, change) => {
    expect(refused(change)).toBe("capture_mismatch");
  });

  it("calendar_missing: the page has no calendar", () => {
    expect(refused((v) => void (v.fixtures = null))).toBe("calendar_missing");
    expect(refused((v) => void (v.fixtures = undefined))).toBe("calendar_missing");
  });

  it("calendar_unreadable: one club under two names, or one name for two clubs", () => {
    expect(
      refused((v) => void (v.fixtures!.gameweeks[20]!.fixtures[0]!.home.name = "Alpha FC")),
    ).toBe("calendar_unreadable");
    expect(refused((v) => void (v.fixtures!.gameweeks[20]!.fixtures[0]!.home.name = "Beta"))).toBe(
      "calendar_unreadable",
    );
  });

  it("calendar_unreadable: two clubs under one name all season", () => {
    expect(
      refused((v) => {
        for (const week of v.fixtures!.gameweeks) {
          for (const match of week.fixtures)
            if (match.away.team_id === 4) match.away.name = "Gamma";
        }
      }),
    ).toBe("calendar_unreadable");
  });

  it("calendar_unreadable is read where the publisher reads it: after the capture and chips", () => {
    const unreadable = (v: MemberChipForecastInputs) =>
      void (v.fixtures!.gameweeks[20]!.fixtures[0]!.home.name = "Beta");
    expect(
      refused((v) => {
        unreadable(v);
        v.squad.chips!.known = false;
      }),
    ).toBe("chip_history_unknown");
    expect(
      refused((v) => {
        unreadable(v);
        v.fixtures!.source_snapshot_id = "another";
      }),
    ).toBe("capture_mismatch");
    // An unreadable calendar states no season, so its season is not compared.
    expect(
      refused((v) => {
        unreadable(v);
        v.fixtures!.season = "2025-26";
      }),
    ).toBe("calendar_unreadable");
  });

  it("fixtures_unscheduled: a fixture has no gameweek yet", () => {
    expect(refused((v) => void (v.fixtures!.unscheduled_count = 2))).toBe("fixtures_unscheduled");
  });

  it("calendar_incomplete: a week inside a held window is missing", () => {
    expect(refused((v) => void v.fixtures!.gameweeks.splice(18, 1))).toBe("calendar_incomplete");
    // A week after every held window is never read.
    expect(
      memberChipForecast(
        (() => {
          const base = inputs();
          base.fixtures!.gameweeks.splice(25, 1);
          return base;
        })(),
      ).status,
    ).toBe("available");
  });

  it("club_roster_missing: the calendar names no club", () => {
    expect(
      refused((v) => {
        for (const week of v.fixtures!.gameweeks) week.fixtures = [];
      }),
    ).toBe("club_roster_missing");
  });

  it("club_roster_incomplete: a squad player's club is not in the calendar", () => {
    expect(refused((v) => void (v.table.players[4]!.team = "Epsilon"))).toBe(
      "club_roster_incomplete",
    );
  });

  it("chip_history_unknown: no chip block, an unknown history, or an unknown window", () => {
    expect(refused((v) => void (v.squad.chips = undefined))).toBe("chip_history_unknown");
    expect(refused((v) => void (v.squad.chips!.known = false))).toBe("chip_history_unknown");
    expect(
      refused(
        (v) => void (v.squad.chips!.states.wildcard!.second_half = window("unknown", 20, 38)),
      ),
    ).toBe("chip_history_unknown");
  });

  it("chip_window_unreadable: two open windows of one chip cover this week", () => {
    expect(
      refused((v) => void (v.squad.chips!.states.bboost!.second_half = window("available", 5, 38))),
    ).toBe("chip_window_unreadable");
  });

  it("squad_projection_missing: a squad player is not in the table", () => {
    expect(refused((v) => void v.table.players.splice(5, 1))).toBe("squad_projection_missing");
  });

  it.each<[string, (value: MemberChipForecastInputs) => void]>([
    ["a table that lists a player twice", (v) => void v.table.players.push(v.table.players[0]!)],
    [
      // 5349883 in the GW6 tree: the captured armband sat on the bench.
      "an armband on the bench",
      (v) => {
        v.squad.starting_xi[0]!.is_captain = false;
        v.squad.bench[2]!.is_captain = true;
      },
    ],
    ["a squad short of fifteen", (v) => void v.squad.bench.pop()],
    [
      "a chip window without its gameweeks",
      (v) =>
        void (v.squad.chips!.states.freehit!.first_half = {
          ...window("available", 2, 19),
          start_event: 2.5,
        }),
    ],
    [
      "a club with projected points in a week it does not play",
      (v) => void (v.fixtures!.gameweeks[6]!.fixtures = [fixture(71, 1, 2)]),
    ],
  ])("forecast_inputs_unreadable: %s", (_, change) => {
    expect(refused(change)).toBe("forecast_inputs_unreadable");
  });
});
