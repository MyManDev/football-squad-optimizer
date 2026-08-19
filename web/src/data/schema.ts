/* Generated from docs/contracts/ui_view_v1.schema.json by npm run gen:types - do not edit. */

/**
 * Every JSON file the site writes is a ViewEnvelope whose payload is one of the view models. Produced by squadopt.application; the frontend renders, never computes.
 */
export interface SquadOptUIViewContract {
  contract_version: "ui_view_v1";
  generated_at_utc: string;
  payload: RecommendationView | PoolView | LeagueView | LedgerView | StatusView | SiteIndex;
}
export interface RecommendationView {
  bench: PlayerView[];
  captain_player_id: number;
  captured_at_utc: string;
  deadline_utc: string;
  decision_kind: "opening" | "transfer";
  feature_contract_version: string;
  gameweek: number;
  metadata: {
    [k: string]: unknown;
  };
  model_name: string;
  model_version: string;
  outcome_net_score: number | null;
  outcome_realized_score: number | null;
  prediction_fingerprint: string;
  projected_score: number;
  report_contract_version: string;
  risk: RiskView;
  season: string;
  settled: boolean;
  snapshot_id: string;
  solver_proved_optimal: boolean;
  solver_status: string;
  squad: PlayerView[];
  starting_xi: PlayerView[];
  total_cost_tenths: number;
  transfers: TransferView | null;
  unavailable_player_count: number;
}
export interface PlayerView {
  bench_order: number | null;
  expected_points: number;
  is_captain: boolean;
  name: string;
  player_id: number;
  position: "GK" | "DEF" | "MID" | "FWD" | "UNK";
  price_tenths: number;
  role: "starter" | "bench" | "out" | "in" | "pool";
  short_name: string;
  team: string;
}
export interface RiskView {
  blockers: string[];
  location_shift_points: number | null;
  lower_quantile_probability: number | null;
  lower_quantile_score: number | null;
  mean_score: number | null;
  mean_worst_fraction_score: number | null;
  points_threshold: number | null;
  probability_below_threshold: number | null;
  /**
   * @minItems 2
   * @maxItems 2
   */
  probability_below_threshold_interval: [number, number] | null;
  reason: string;
  residual_source: string | null;
  rivals: RivalComparisonView[];
  scenario_count: number | null;
  stated_limits: string[];
  status: "available" | "unavailable" | "not_requested";
  worst_fraction: number | null;
}
export interface RivalComparisonView {
  mean_difference: number;
  probability_ahead: number;
  /**
   * @minItems 2
   * @maxItems 2
   */
  probability_ahead_interval: [number, number];
  rival: string;
  shared_starters: number;
}
export interface TransferView {
  bank_after_tenths: number;
  bank_before_tenths: number;
  chip: string | null;
  chips_available: string[];
  free_transfers_after: number;
  free_transfers_before: number;
  max_free_transfers: number;
  paid_transfer_count: number;
  planner_solver_status: string;
  previous_gameweek: number;
  squad_sell_value_tenths: number;
  transfer_count: number;
  transfer_hit_cost_points: number;
  transfer_hit_points: number;
  transfers_in: PlayerView[];
  transfers_out: PlayerView[];
}
export interface PoolView {
  gameweek: number;
  per_position: number;
  players: PoolPlayerView[];
  pool_size: number;
  season: string;
}
export interface PoolPlayerView {
  expected_points: number;
  name: string;
  player_id: number;
  position: "GK" | "DEF" | "MID" | "FWD";
  price_tenths: number;
  rank_in_position: number;
  role: "starter" | "bench" | "pool";
  selected: boolean;
  short_name: string;
  team: string;
}
export interface LeagueView {
  captured_at_utc: string;
  league_total_average_score: number | null;
  our_total_realized_net_score: number | null;
  ownership: OwnershipView | null;
  scored_gameweeks: number;
  season: string;
  source_snapshot_id: string;
  total_difference_to_average: number | null;
  verdict: string;
  weeks: LeagueWeekView[];
}
export interface OwnershipView {
  differential_threshold_percent: number;
  differentials: number[];
  effective_ownership: number;
  gameweek: number;
  least_owned_starter: number | null;
  mean_starter_ownership: number;
  most_owned_starter: number | null;
  ownership_percent: {
    [k: string]: number;
  };
  squad: PlayerView[];
}
export interface LeagueWeekView {
  average_entry_score: number | null;
  deadline_utc: string;
  difference_to_average: number | null;
  finished: boolean;
  gameweek: number;
  highest_score: number | null;
  our_projected_score: number | null;
  our_realized_net_score: number | null;
  our_realized_score: number | null;
}
export interface LedgerView {
  chips_played: string[];
  decided_gameweeks: number;
  rows: LedgerRowView[];
  season: string;
  settled_gameweeks: number;
  total_projected_score: number;
  total_projected_score_settled: number | null;
  total_projection_error: number | null;
  total_realized_net_score: number | null;
  total_realized_score: number | null;
  total_transfer_hit_points: number;
}
export interface LedgerRowView {
  captain_player_id: number;
  chip: string | null;
  cumulative_projected_score: number;
  cumulative_realized_score: number | null;
  deadline_utc: string;
  decision_kind: "opening" | "transfer";
  gameweek: number;
  projected_score: number;
  projection_error: number | null;
  realized_net_score: number | null;
  realized_score: number | null;
  settled: boolean;
  snapshot_id: string;
  solver_status: string;
  transfer_count: number;
  transfer_hit_points: number;
  unavailable_player_count: number;
}
export interface StatusView {
  actions: TickActionView[];
  decided_gameweeks: number[];
  hours_to_deadline: number | null;
  is_idle: boolean;
  latest_capture: string | null;
  next_deadline_utc: string | null;
  next_gameweek: number | null;
  now_utc: string;
  recent_events: RunLogEventView[];
  season: string | null;
  settled_gameweeks: number[];
  tick_contract_version: string;
}
export interface TickActionView {
  gameweek: number | null;
  handoff_path: string | null;
  kind: "capture" | "decide" | "settle" | "wait";
  reason: string;
  snapshot_id: string | null;
}
export interface RunLogEventView {
  fields: {
    [k: string]: unknown;
  };
  level: string;
  message: string;
  run_id: string;
  ts: string;
}
export interface SiteIndex {
  files: string[];
  gameweeks: {
    [k: string]: number[];
  };
  generated_at_utc: string;
  latest: {
    gameweek: number;
    path: string;
    season: string;
  } | null;
  schema_path: string;
  seasons: string[];
}
