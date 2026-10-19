/**
 * The chip timing card's rows: the rule's document read under the game's one chip per
 * gameweek. The rule decides each chip alone; the measured planner played at most one chip
 * a gameweek and chose the one furthest above its threshold, so the card does the same.
 * The document is never changed: this is the display only.
 *
 * - Several chips to play this week: the largest `gain_this_week - threshold_this_week`
 *   keeps this week, a tie going to the game's order; the others read not this week.
 * - Triple Captain and Bench Boost naming the same later gameweek: the larger
 *   `estimated_gain - threshold` keeps it, a tie going to the game's order; the other moves
 *   to its next later gameweek where the rule's loop crosses its threshold, or reads not
 *   this week where none does.
 * - A chip whose gain this week is unknown, or whose window is not the current one, has no
 *   row.
 */

import { CHIP_NAMES, type ChipName, type ChipReading, type PointsAt } from "./rule";

export type ChipTimingWhen =
  | { kind: "this-week"; gain: number }
  | { kind: "gameweek"; gameweek: number; gain: number; playerIds: number[] }
  | { kind: "not-this-week"; lastGameweek: number };

export interface ChipTimingRow {
  name: ChipName;
  when: ChipTimingWhen;
}

/** The rule's next named gameweek for a chip after `after`, on the reading's own inputs. */
export type NextPointsAt = (name: ChipName, after: number) => PointsAt | null;

/** The one of two candidates the game's single chip keeps: the larger margin, then the game's order. */
function keeps<T extends { name: ChipName; margin: number }>(a: T, b: T): T {
  if (a.margin !== b.margin) return a.margin > b.margin ? a : b;
  return CHIP_NAMES.indexOf(a.name) <= CHIP_NAMES.indexOf(b.name) ? a : b;
}

export function chipTimingRows(
  forecast: { chips: readonly ChipReading[] },
  next: NextPointsAt,
): ChipTimingRow[] {
  const shown = forecast.chips.filter(
    (chip) => chip.verdict === "play_now" || chip.verdict === "hold",
  );
  const playing = shown
    .filter((chip) => chip.verdict === "play_now")
    .map((chip) => ({
      name: chip.name,
      margin: chip.gain_this_week! - chip.threshold_this_week!,
    }));
  const thisWeek = playing.length > 0 ? playing.reduce(keeps).name : null;
  const named = new Map<ChipName, PointsAt | null>(
    shown
      .filter((chip) => chip.verdict === "hold")
      .map((chip) => [chip.name, chip.points_at_gameweek]),
  );
  const captain = named.get("3xc");
  const bench = named.get("bboost");
  if (captain && bench && captain.gameweek === bench.gameweek) {
    const kept = keeps(
      { name: "3xc" as ChipName, margin: captain.estimated_gain - captain.threshold },
      { name: "bboost" as ChipName, margin: bench.estimated_gain - bench.threshold },
    ).name;
    const moved: ChipName = kept === "3xc" ? "bboost" : "3xc";
    named.set(moved, next(moved, captain.gameweek));
  }
  return shown.map((chip): ChipTimingRow => {
    const notThisWeek: ChipTimingRow = {
      name: chip.name,
      when: { kind: "not-this-week", lastGameweek: chip.window.last_gameweek },
    };
    if (chip.verdict === "play_now") {
      return chip.name === thisWeek
        ? { name: chip.name, when: { kind: "this-week", gain: chip.gain_this_week! } }
        : notThisWeek;
    }
    const at = named.get(chip.name) ?? null;
    return at === null
      ? notThisWeek
      : {
          name: chip.name,
          when: {
            kind: "gameweek",
            gameweek: at.gameweek,
            gain: at.estimated_gain,
            playerIds: at.player_ids,
          },
        };
  });
}
