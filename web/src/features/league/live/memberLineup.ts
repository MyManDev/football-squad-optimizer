import type { MemberWeek } from "../../liveScore/weekLive";
import type { DevicePlanDocument } from "../device/types";
import type { EntrySquad, EntrySquadPlayer } from "../types";

export type PlayedLineup = Pick<EntrySquad, "starting_xi" | "bench" | "gameweek" | "active_chip">;

/** Actual picks and unmultiplied FPL points; absent scores stay absent. */
export function memberLineup(
  member: MemberWeek,
  table: DevicePlanDocument,
  points: ReadonlyMap<number, number> = new Map(),
): PlayedLineup | null {
  const players = new Map(table.players.map((player) => [player.element_id, player]));
  if (member.pick_order.some((element) => !players.has(element))) return null;
  const fifteen = member.pick_order.map((element, index): EntrySquadPlayer => {
    const player = players.get(element)!;
    return {
      player_id: player.id,
      name: player.name,
      short_name: player.short_name,
      team: player.team,
      position: ["GK", "DEF", "MID", "FWD"].includes(player.position)
        ? (player.position as EntrySquadPlayer["position"])
        : "UNK",
      price_tenths: player.buy_tenths,
      expected_points: player.expected_points,
      event_points: points.get(element) ?? null,
      is_captain: element === member.captain,
      is_vice_captain: element === member.vice,
      role: index < 11 ? "starter" : "bench",
      bench_order: index < 11 ? null : index - 10,
    };
  });
  return {
    starting_xi: fifteen.slice(0, 11),
    bench: fifteen.slice(11),
    gameweek: member.gameweek,
    active_chip: member.active_chip,
  };
}

/**
 * The chip record with the live week's chip written in. The published record is read before
 * the deadline, so a chip the member played at it still stands as available there; the live
 * read names the chip, and the record shown after the deadline says it was played that week.
 */
export function chipsWithPlayedWeek(
  squad: Pick<EntrySquad, "chips_used" | "chips">,
  lineup: Pick<PlayedLineup, "active_chip" | "gameweek">,
): Pick<EntrySquad, "chips_used" | "chips"> {
  const chip = lineup.active_chip;
  const week = lineup.gameweek;
  if (!chip) return { chips_used: squad.chips_used, chips: squad.chips };
  const played = squad.chips_used?.[chip] ?? [];
  const chips_used =
    squad.chips_used === null || played.includes(week)
      ? squad.chips_used
      : { ...squad.chips_used, [chip]: [...played, week].sort((a, b) => a - b) };
  const windows = squad.chips?.known ? squad.chips.states[chip] : undefined;
  if (!squad.chips || !windows) return { chips_used, chips: squad.chips };
  const halves = { ...windows };
  for (const half of ["first_half", "second_half"] as const) {
    const window = halves[half];
    if (
      window &&
      window.state !== "used" &&
      window.start_event <= week &&
      week <= window.stop_event
    )
      halves[half] = { ...window, state: "used", gameweek: week };
  }
  return {
    chips_used,
    chips: { ...squad.chips, states: { ...squad.chips.states, [chip]: halves } },
  };
}

/**
 * The squad a page shows once its deadline has passed. The free transfer count was the
 * passed deadline's, so it is no longer stated. With the live week read, the picks and the
 * chip are the ones played; until then the historical event points are cleared.
 */
export function squadWithPlayedWeek(squad: EntrySquad, lineup: PlayedLineup | null): EntrySquad {
  if (lineup !== null)
    return {
      ...squad,
      ...lineup,
      ...chipsWithPlayedWeek(squad, lineup),
      free_transfers_known: false,
    };
  return {
    ...squad,
    free_transfers_known: false,
    starting_xi: squad.starting_xi.map((player) => ({ ...player, event_points: null })),
    bench: squad.bench.map((player) => ({ ...player, event_points: null })),
  };
}
