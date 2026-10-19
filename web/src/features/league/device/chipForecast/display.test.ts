import { describe, expect, it, vi } from "vitest";

import { chipTimingRows } from "./display";
import {
  chipForecast,
  nextPointsAt,
  type ChipForecastInputs,
  type ChipName,
  type ChipReading,
  type PointsAt,
} from "./rule";

/** One chip's reading as the rule writes it, window 1 to 19 unless named. */
function chip(name: ChipName, fields: Partial<ChipReading>): ChipReading {
  return {
    name,
    window: { first_gameweek: 1, last_gameweek: 19 },
    holding_value: 12,
    verdict: "hold",
    hold_reason: "gain_not_above_threshold",
    gain_this_week: 1,
    threshold_this_week: 5,
    reservation_allows_this_week: true,
    points_at_gameweek: null,
    structured_gameweeks: null,
    ...fields,
  };
}

function at(gameweek: number, estimated_gain: number, threshold: number, ids = [7]): PointsAt {
  return { gameweek, estimated_gain, threshold, player_ids: ids };
}

const never = () => {
  throw new Error("No chip should move.");
};

describe("one chip a gameweek on the card", () => {
  it("names the chip furthest above its threshold this week, and the other not this week", () => {
    // 6879786 on the GW6 tree: Wildcard by 2.75, Free Hit by 0.46.
    const forecast = {
      chips: [
        chip("wildcard", {
          verdict: "play_now",
          hold_reason: null,
          gain_this_week: 11.93,
          threshold_this_week: 9.18,
          window: { first_gameweek: 2, last_gameweek: 19 },
        }),
        chip("freehit", {
          verdict: "play_now",
          hold_reason: null,
          gain_this_week: 11.93,
          threshold_this_week: 11.47,
          window: { first_gameweek: 2, last_gameweek: 19 },
        }),
      ],
    };
    const before = structuredClone(forecast);
    expect(chipTimingRows(forecast, never)).toEqual([
      { name: "wildcard", when: { kind: "this-week", gain: 11.93 } },
      { name: "freehit", when: { kind: "not-this-week", lastGameweek: 19 } },
    ]);
    // The document stays as the rule wrote it.
    expect(forecast).toEqual(before);
  });

  it("gives this week to the larger margin, not the larger gain", () => {
    const rows = chipTimingRows(
      {
        chips: [
          chip("freehit", {
            verdict: "play_now",
            gain_this_week: 14,
            threshold_this_week: 12,
          }),
          chip("bboost", { verdict: "play_now", gain_this_week: 9, threshold_this_week: 4 }),
        ],
      },
      never,
    );
    expect(rows.map((row) => [row.name, row.when.kind])).toEqual([
      ["freehit", "not-this-week"],
      ["bboost", "this-week"],
    ]);
  });

  it("breaks a tie this week by the game's order", () => {
    const rows = chipTimingRows(
      {
        chips: [
          chip("freehit", { verdict: "play_now", gain_this_week: 10, threshold_this_week: 8 }),
          chip("3xc", { verdict: "play_now", gain_this_week: 7, threshold_this_week: 5 }),
        ],
      },
      never,
    );
    expect(rows.map((row) => row.when.kind)).toEqual(["this-week", "not-this-week"]);
  });

  it("keeps a gameweek both name for the larger margin and moves the other to its next", () => {
    const next = vi.fn(() => at(15, 6.5, 5.56, [12, 13, 14, 15]));
    const rows = chipTimingRows(
      {
        chips: [
          chip("bboost", { points_at_gameweek: at(12, 9, 7.78, [12, 13, 14, 15]) }),
          chip("3xc", { points_at_gameweek: at(12, 10, 7) }),
        ],
      },
      next,
    );
    // Triple Captain by 3.00 over Bench Boost's 1.22: Bench Boost moves on from gameweek 12.
    expect(next).toHaveBeenCalledExactlyOnceWith("bboost", 12);
    expect(rows).toEqual([
      {
        name: "bboost",
        when: { kind: "gameweek", gameweek: 15, gain: 6.5, playerIds: [12, 13, 14, 15] },
      },
      { name: "3xc", when: { kind: "gameweek", gameweek: 12, gain: 10, playerIds: [7] } },
    ]);
  });

  it("reads not this week for the chip that moves where no later gameweek crosses", () => {
    const next = vi.fn(() => null);
    const rows = chipTimingRows(
      {
        chips: [
          chip("bboost", { points_at_gameweek: at(18, 12, 2.22) }),
          chip("3xc", {
            points_at_gameweek: at(18, 4, 2),
            window: { first_gameweek: 1, last_gameweek: 18 },
          }),
        ],
      },
      next,
    );
    expect(next).toHaveBeenCalledExactlyOnceWith("3xc", 18);
    expect(rows[0]!.when).toEqual({ kind: "gameweek", gameweek: 18, gain: 12, playerIds: [7] });
    expect(rows[1]!.when).toEqual({ kind: "not-this-week", lastGameweek: 18 });
  });

  it("breaks a tie on the same gameweek by the game's order: Bench Boost before Triple Captain", () => {
    const next = vi.fn(() => null);
    chipTimingRows(
      {
        chips: [
          chip("bboost", { points_at_gameweek: at(12, 9, 7) }),
          chip("3xc", { points_at_gameweek: at(12, 8, 6) }),
        ],
      },
      next,
    );
    expect(next).toHaveBeenCalledExactlyOnceWith("3xc", 12);
  });

  it("moves nothing where the two name different gameweeks", () => {
    const rows = chipTimingRows(
      {
        chips: [
          chip("bboost", { points_at_gameweek: at(14, 9, 7) }),
          chip("3xc", { points_at_gameweek: at(12, 8, 6) }),
        ],
      },
      never,
    );
    expect(rows.map((row) => row.when.kind === "gameweek" && row.when.gameweek)).toEqual([14, 12]);
  });

  it("names the window's last gameweek for a held chip with no named gameweek", () => {
    expect(
      chipTimingRows(
        { chips: [chip("wildcard", { window: { first_gameweek: 2, last_gameweek: 19 } })] },
        never,
      ),
    ).toEqual([{ name: "wildcard", when: { kind: "not-this-week", lastGameweek: 19 } }]);
  });

  it("has no row for an unknown gain, nor for a window that is not the current one", () => {
    expect(
      chipTimingRows(
        {
          chips: [
            chip("wildcard", { verdict: "unknown_this_week", hold_reason: null }),
            chip("freehit", { verdict: "window_not_open", hold_reason: null }),
            chip("bboost", { verdict: "expired_window", hold_reason: null }),
          ],
        },
        never,
      ),
    ).toEqual([]);
  });

  it("leaves an unknown chip out of the choice this week", () => {
    const rows = chipTimingRows(
      {
        chips: [
          chip("wildcard", { verdict: "unknown_this_week", gain_this_week: null }),
          chip("freehit", { verdict: "play_now", gain_this_week: 9, threshold_this_week: 8 }),
        ],
      },
      never,
    );
    expect(rows).toEqual([{ name: "freehit", when: { kind: "this-week", gain: 9 } }]);
  });
});

/**
 * Gameweek 10 of windows 1 (2 for Wildcard and Free Hit) to 19, one fixture a club a week.
 * Player 1 (club 1) is the captain at 5 points; the bench, clubs 12 to 15, is four players
 * at 1.5. In gameweek 12 club 1 and the bench's clubs 12 and 13 play twice.
 */
function inputs(): ChipForecastInputs {
  const clubs = Array.from({ length: 20 }, (_, index) => index + 1);
  return {
    decision_gameweek: 10,
    chips: [
      { name: "wildcard", first_gameweek: 2, last_gameweek: 19, gain_this_week: 11 },
      { name: "freehit", first_gameweek: 2, last_gameweek: 19, gain_this_week: 11 },
      { name: "bboost", first_gameweek: 1, last_gameweek: 19, gain_this_week: 3 },
      { name: "3xc", first_gameweek: 1, last_gameweek: 19, gain_this_week: 4 },
    ],
    squad: Array.from({ length: 15 }, (_, index) => ({
      player_id: index + 1,
      club_id: index + 1,
      position: index === 0 ? ("GK" as const) : ("MID" as const),
      expected_points: index === 0 ? 5 : index < 11 ? 2 : 1.5,
      bench_order: index < 11 ? null : index - 10,
      is_captain: index === 0,
    })),
    calendar: Array.from({ length: 10 }, (_, index) => ({
      gameweek: 10 + index,
      fixture_count_by_club: Object.fromEntries(
        clubs.map((club) => [club, 10 + index === 12 && [1, 12, 13].includes(club) ? 2 : 1]),
      ),
    })),
    holding_values: { bboost: 20, "3xc": 18, wildcard: 12, freehit: 15 },
    threshold: "decaying",
    reserve: false,
  };
}

describe("the card over the rule itself", () => {
  it("moves Bench Boost from the gameweek Triple Captain keeps to the next one the loop crosses", () => {
    const forecast = chipForecast(inputs());
    const named = Object.fromEntries(
      forecast.chips.map((reading) => [reading.name, reading.points_at_gameweek?.gameweek]),
    );
    // Both name gameweek 12 in the document, which stays as the rule wrote it.
    expect(named).toMatchObject({ bboost: 12, "3xc": 12 });
    const rows = chipTimingRows(forecast, (name, after) => nextPointsAt(inputs(), name, after));
    // Triple Captain: 10 against 7.00. Bench Boost: 9 against 7.78, then 6 against 6.67 in
    // gameweek 13 and against 5.56 in gameweek 14.
    expect(rows).toEqual([
      { name: "wildcard", when: { kind: "this-week", gain: 11 } },
      { name: "freehit", when: { kind: "not-this-week", lastGameweek: 19 } },
      {
        name: "bboost",
        when: { kind: "gameweek", gameweek: 14, gain: 6, playerIds: [12, 13, 14, 15] },
      },
      { name: "3xc", when: { kind: "gameweek", gameweek: 12, gain: 10, playerIds: [1] } },
    ]);
  });

  it("finds the same first gameweek the document names when asked from this week", () => {
    const forecast = chipForecast(inputs());
    for (const reading of forecast.chips) {
      expect(nextPointsAt(inputs(), reading.name, 10)).toEqual(reading.points_at_gameweek);
    }
    expect(nextPointsAt(inputs(), "bboost", 19)).toBeNull();
  });
});
