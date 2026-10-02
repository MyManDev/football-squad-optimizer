/**
 * The two published documents a member's device needs to solve its own one-week plan,
 * and the answer the solve returns. Shapes mirror `squadopt.application.device_plan`.
 */

export const DEVICE_PLAN_CONTRACT_VERSION = "league_device_plan_v1";

export interface DevicePlanPlayer {
  id: number;
  name: string;
  short_name: string;
  team: string;
  position: string;
  buy_tenths: number;
  expected_points: number;
  /** (squad, starter, captain): the server's exact integer objective coefficients. */
  coefficients: [number, number, number];
}

export interface DevicePlanRules {
  squad_size: number;
  starting_size: number;
  squad_position_limits: Record<string, number>;
  starting_position_min: Record<string, number>;
  starting_position_max: Record<string, number>;
  max_players_per_team: number;
  max_free_transfers: number;
  /** The planner's caution margin per paid transfer, on the objective's integer scale. */
  hit_cost_scaled: number;
  /** What the game charges per paid transfer, in points. */
  hit_points_charged: number;
  expected_points_scale: number;
}

/** `league/device-plan.json`: the capture's table in solver order, and the rules as numbers. */
export interface DevicePlanDocument {
  contract_version: typeof DEVICE_PLAN_CONTRACT_VERSION;
  league_id: number;
  season: string;
  gameweek: number;
  source_snapshot_id: string;
  policy_id: string;
  rules: DevicePlanRules;
  players: DevicePlanPlayer[];
}

/** One member's side of the problem, from `entries/<id>.json`. */
export interface DevicePlanEntry {
  held: number[];
  bank_tenths: number;
  free_transfers: number;
  /** Sale price of each held player, keyed by player id as text. */
  sell_tenths: Record<string, number>;
}

/** What the device's solve proved, in player ids. */
export interface DevicePlanAnswer {
  /** The objective on the integer scale, and the same divided by the scale. */
  objective_scaled: number;
  objective: number;
  squad: number[];
  starting_xi: number[];
  captain: number;
  vice_captain: number;
  /** Bench in the order the game walks it: the goalkeeper, then outfield by points. */
  bench: number[];
  transfers_in: number[];
  transfers_out: number[];
  /** Paid transfers times what the game charges for one. */
  transfer_hit_points: number;
  /** The eleven with the captain doubled, for the plan and for holding the fifteen. */
  expected_own_points: number;
  hold_points: number;
  seconds: number;
}

function finite(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function numberMap(value: unknown): value is Record<string, number> {
  return record(value) && Object.values(value).every(finite);
}

function isPlayer(value: unknown): value is DevicePlanPlayer {
  if (!record(value)) return false;
  return (
    finite(value.id) &&
    typeof value.name === "string" &&
    typeof value.short_name === "string" &&
    typeof value.team === "string" &&
    typeof value.position === "string" &&
    finite(value.buy_tenths) &&
    finite(value.expected_points) &&
    Array.isArray(value.coefficients) &&
    value.coefficients.length === 3 &&
    value.coefficients.every(finite)
  );
}

export function isDevicePlanDocument(value: unknown): value is DevicePlanDocument {
  if (!record(value) || value.contract_version !== DEVICE_PLAN_CONTRACT_VERSION) return false;
  const rules = value.rules;
  if (!record(rules)) return false;
  return (
    finite(value.league_id) &&
    typeof value.season === "string" &&
    finite(value.gameweek) &&
    typeof value.source_snapshot_id === "string" &&
    typeof value.policy_id === "string" &&
    finite(rules.squad_size) &&
    finite(rules.starting_size) &&
    numberMap(rules.squad_position_limits) &&
    numberMap(rules.starting_position_min) &&
    numberMap(rules.starting_position_max) &&
    finite(rules.max_players_per_team) &&
    finite(rules.max_free_transfers) &&
    finite(rules.hit_cost_scaled) &&
    finite(rules.hit_points_charged) &&
    finite(rules.expected_points_scale) &&
    rules.expected_points_scale > 0 &&
    Array.isArray(value.players) &&
    value.players.length > 0 &&
    value.players.every(isPlayer)
  );
}

export function isDevicePlanEntry(value: unknown): value is DevicePlanEntry {
  if (!record(value)) return false;
  return (
    Array.isArray(value.held) &&
    value.held.every(finite) &&
    finite(value.bank_tenths) &&
    finite(value.free_transfers) &&
    numberMap(value.sell_tenths)
  );
}
