/**
 * The device's answer as the advice document the page already reads: the same fields
 * the published one-week pure-points plan carries, with a chip played or a rival
 * strategy's account where one was asked for, built from the published inputs and what
 * the solve proved. Nothing is stated that the solve did not prove or the documents do
 * not say.
 */

import type { AdvicePlayer, EntryAdvice, EntrySquad, LeagueViewEnvelope } from "../types";
import type { DevicePlanAnswer, DevicePlanDocument, DevicePlanPlayer } from "./types";

/** The server's name for how a chip's gain is measured: this gameweek's expected points. */
export const CHIP_CHOICE_BASIS = "one_week_expected_points_v1";
/** The server's name for what a Top 100 price is measured on: the base model's points. */
export const TOP100_PRICE_BASIS = "base_model_pure_points_v1";

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
  squad: Pick<EntrySquad, "entry" | "free_transfers_known" | "purchase_prices_known" | "chips">,
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
    mode: answer.rival?.mode ?? "saf-puan",
    window: 1,
    source_snapshot_id: document.source_snapshot_id,
    moves: answer.moves.map((move, index) => ({
      move_id: `gw${String(gameweek).padStart(2, "0")}-${index + 1}`,
      player_out: player(move.out),
      player_in: player(move.in),
      expected_points_delta: move.gain,
      // As the server labels a one-week plan's moves: the pure-points plan's are a points
      // gain, a rival strategy's are its trade-off (build_advice_payload's default by mode).
      reason_code: answer.rival === undefined ? "points_gain" : "mode_tradeoff",
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
    chip: answer.chip,
    solver_status: "OPTIMAL",
    optimality_gap: 0,
    data_quality: missing.length ? "partial" : "complete",
    missing_fields: missing,
  };
  if (answer.top100 !== undefined) {
    // The weight's account: the price on base points against the member's own plan, the
    // rows' reasons, and the counts' source as the document states it.
    const top100 = answer.top100;
    payload.expected_points_cost = top100.expected_points_cost;
    payload.expected_points_cost_ceiling = top100.expected_points_cost_ceiling;
    payload.control_solver_status = "OPTIMAL";
    payload.control_optimality_gap = 0;
    payload.moves = payload.moves.map((move, index) => ({
      ...move,
      reason_code: top100.reasons[index] ?? move.reason_code,
    }));
    const source = document.rules.top100;
    payload.top100 = {
      weight: top100.weight,
      changed: top100.changed,
      price_basis: TOP100_PRICE_BASIS,
      ...(source
        ? {
            cohort_snapshot_id: source.cohort_snapshot_id,
            picks_snapshot_id: source.picks_snapshot_id,
            table_sha256: source.table_sha256,
            picks_gameweek: source.picks_gameweek,
          }
        : {}),
    };
  }
  if (answer.rival !== undefined) {
    // The band's account, as the server publishes it: every solve here was proved, so
    // the price carries its ceiling and the control its proof.
    const rival = answer.rival;
    payload.rival_entry_id = rival.rival_entry_id;
    payload.rival_label = `entry-${rival.rival_entry_id}`;
    payload.expected_points_cost = rival.expected_points_cost;
    payload.expected_points_cost_ceiling = rival.expected_points_cost_ceiling;
    payload.overlap_count = rival.overlap_count;
    payload.expected_gap_vs_rival = rival.expected_gap_vs_rival;
    payload.captain_agreement = rival.captain_agreement;
    payload.transfer_cap = rival.transfer_cap;
    payload.overlap_target = rival.overlap_target;
    payload.overlap_applied = rival.overlap_applied;
    payload.plan_kind = rival.plan_kind;
    payload.alternative_plan = rival.alternative_plan;
    payload.control_solver_status = "OPTIMAL";
    payload.control_optimality_gap = 0;
  }
  if (answer.chip !== null && answer.gain_vs_no_chip !== undefined) {
    // The chip is measured against the member's own no-chip plan, which the device
    // solved beside it and proved; the windows are the ones the squad document states.
    payload.control_solver_status = "OPTIMAL";
    payload.control_optimality_gap = 0;
    payload.chip_choice = {
      chip: answer.chip,
      gain_vs_no_chip: answer.gain_vs_no_chip,
      basis: CHIP_CHOICE_BASIS,
      ...(squad.chips?.states[answer.chip]
        ? { windows_left: squad.chips.states[answer.chip] }
        : {}),
    };
  }
  return {
    contract_version: "provisional_league_ui_v1",
    generated_at_utc: generatedAt.toISOString().replace(/\.\d{3}Z$/, "Z"),
    source_kind: "live",
    payload,
  };
}
