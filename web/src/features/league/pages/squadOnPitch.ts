import type { BenchPlayer, PitchPlayer } from "../components/MemberPitch";
import type { EntryAdvice, EntrySquad, EntrySquadPlayer } from "../types";

/** The squad the pitch draws: the plan's, or the one held while no plan is shown. */
export interface SquadOnPitch {
  /** 'plan' after the plan's transfers, 'held' the published squad, null when neither. */
  source: "plan" | "held" | null;
  eleven: PitchPlayer[];
  bench: BenchPlayer[];
}

export const finite = (value: unknown): value is number =>
  typeof value === "number" && Number.isFinite(value);

/** The held bench in its published order; a player with no published order goes last. */
export function heldBench(bench: readonly EntrySquadPlayer[]): EntrySquadPlayer[] {
  return [...bench].sort(
    (left, right) =>
      (left.bench_order ?? Number.MAX_SAFE_INTEGER) -
      (right.bench_order ?? Number.MAX_SAFE_INTEGER),
  );
}

/**
 * The eleven and the bench the page draws. A plan that publishes its eleven is drawn after
 * its transfers, with its armband and the players its moves bring in; otherwise the squad
 * the member holds is drawn, with the captain the game records and no vice-captain, which
 * the published squad does not name.
 */
export function squadOnPitch(plan: EntryAdvice | null, squad: EntrySquad): SquadOnPitch {
  const planned = plan?.starting_xi;
  if (plan && planned && planned.length > 0) {
    const incoming = new Set(
      plan.moves
        .map((move) => move.player_in?.player_id)
        .filter((id): id is number => typeof id === "number"),
    );
    return {
      source: "plan",
      eleven: planned.map((player) => ({
        playerId: player.player_id,
        name: player.name,
        shortName: player.short_name,
        position: player.position,
        team: player.team,
        expectedPoints: finite(player.expected_points) ? player.expected_points : null,
        captain: player.player_id === plan.captain?.player_id,
        vice: player.player_id === plan.vice_captain?.player_id,
        isNew: incoming.has(player.player_id),
      })),
      bench: (plan.bench ?? []).map((player, index) => ({
        playerId: player.player_id,
        name: player.name,
        shortName: player.short_name,
        position: player.position,
        team: player.team,
        expectedPoints: finite(player.expected_points) ? player.expected_points : null,
        order: index + 1,
      })),
    };
  }
  if (squad.starting_xi.length > 0) {
    return {
      source: "held",
      eleven: squad.starting_xi.map((player) => ({
        playerId: player.player_id,
        name: player.name,
        shortName: player.short_name,
        position: player.position,
        team: player.team,
        expectedPoints: finite(player.expected_points) ? player.expected_points : null,
        captain: player.is_captain,
        vice: false,
        isNew: false,
      })),
      bench: heldBench(squad.bench).map((player) => ({
        playerId: player.player_id,
        name: player.name,
        shortName: player.short_name,
        position: player.position,
        team: player.team,
        expectedPoints: finite(player.expected_points) ? player.expected_points : null,
        order: player.bench_order,
      })),
    };
  }
  return { source: null, eleven: [], bench: [] };
}

/** Whether the producer published the whole week's lineup: armband, eleven and bench. */
export function hasLineup(view: EntryAdvice): boolean {
  return Boolean(view.captain && view.vice_captain && view.starting_xi && view.bench);
}
