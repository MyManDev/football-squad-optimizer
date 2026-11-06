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

/** Clear historical event points until this page's live week has actually been read. */
export function squadWithPlayedWeek(squad: EntrySquad, lineup: PlayedLineup | null): EntrySquad {
  if (lineup !== null) return { ...squad, ...lineup };
  return {
    ...squad,
    starting_xi: squad.starting_xi.map((player) => ({ ...player, event_points: null })),
    bench: squad.bench.map((player) => ({ ...player, event_points: null })),
  };
}
