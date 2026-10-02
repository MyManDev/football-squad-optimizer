/**
 * The device's answer as the advice document the page already reads: the same fields
 * the published one-week pure-points plan carries, built from the two published inputs
 * and what the solve proved. Nothing is stated that the solve did not prove or the
 * documents do not say.
 */

import type { AdvicePlayer, EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";
import type { DevicePlanAnswer, DevicePlanDocument, DevicePlanPlayer } from "./types";

export const DEVICE_SOLVER = "highs-wasm";

function position(value: string): AdvicePlayer["position"] {
  return value === "GK" || value === "DEF" || value === "MID" || value === "FWD" ? value : "UNK";
}

function advicePlayer(player: DevicePlanPlayer): AdvicePlayer {
  return {
    player_id: player.id,
    name: player.name,
    short_name: player.short_name,
    position: position(player.position),
    team: player.team,
    expected_points: player.expected_points,
  };
}

/**
 * The advice envelope for a plan the member's device solved. `generatedAt` is the
 * instant the device finished, which the panel prints as the result's date.
 */
export function deviceAdviceEnvelope(
  document: DevicePlanDocument,
  squad: Pick<EntrySquad, "entry" | "free_transfers_known" | "purchase_prices_known">,
  answer: DevicePlanAnswer,
  generatedAt: Date,
): LeagueViewEnvelope<EntryAdvice> {
  // As the advice derives them: a count or a price the source did not state is named.
  const missing: string[] = [];
  if (!squad.free_transfers_known) missing.push("free_transfers");
  if (!squad.purchase_prices_known) missing.push("purchase_prices");
  const byId = new Map(document.players.map((player) => [player.id, player]));
  const player = (id: number | null): AdvicePlayer | null => {
    const row = id === null ? undefined : byId.get(id);
    return row === undefined ? null : advicePlayer(row);
  };
  const gameweek = document.gameweek;
  const payload: EntryAdvice = {
    league_id: document.league_id,
    season: document.season,
    gameweek,
    entry_id: squad.entry.entry_id,
    mode: "saf-puan",
    window: 1,
    source_snapshot_id: document.source_snapshot_id,
    moves: answer.moves.map((move, index) => ({
      move_id: `gw${String(gameweek).padStart(2, "0")}-${index + 1}`,
      player_out: player(move.out),
      player_in: player(move.in),
      expected_points_delta: move.gain,
      reason_code: "points_gain",
    })),
    transfer_hit_points: answer.transfer_hit_points,
    expected_gain_vs_hold: answer.expected_gain_vs_hold,
    expected_own_points: answer.expected_own_points,
    captain: player(answer.captain),
    vice_captain: player(answer.vice_captain),
    starting_xi: answer.starting_xi
      .map((id) => player(id))
      .filter((p): p is AdvicePlayer => p !== null),
    bench: answer.bench.map((id) => player(id)).filter((p): p is AdvicePlayer => p !== null),
    chip: null,
    solver_status: "OPTIMAL",
    optimality_gap: 0,
    data_quality: missing.length ? "partial" : "complete",
    missing_fields: missing,
  };
  return {
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: generatedAt.toISOString().replace(/\.\d{3}Z$/, "Z"),
    source_kind: "live",
    payload,
  };
}
