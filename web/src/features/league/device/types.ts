/**
 * The two published documents a member's device needs to solve its own one-week plan,
 * and the answer the solve returns. Shapes mirror `squadopt.application.device_plan`.
 */

export const DEVICE_PLAN_CONTRACT_VERSION = "league_device_plan_v1";

/** The chips a member may play in the decided week, as the game names them. */
export const DEVICE_CHIPS = ["wildcard", "freehit", "bboost", "3xc"] as const;
export type DeviceChip = (typeof DEVICE_CHIPS)[number];

export function isDeviceChip(value: unknown): value is DeviceChip {
  return typeof value === "string" && (DEVICE_CHIPS as readonly string[]).includes(value);
}

/** The strategies with a rival's eleven as a constraint, as the catalogue names them. */
export const RIVAL_STRATEGIES = ["ortak-koru", "fark-yarat"] as const;
export type RivalStrategy = (typeof RIVAL_STRATEGIES)[number];

export function isRivalStrategy(value: unknown): value is RivalStrategy {
  return typeof value === "string" && (RIVAL_STRATEGIES as readonly string[]).includes(value);
}

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
  /** The same on the objective scale; absent on documents from before the field. */
  hit_charged_scaled?: number;
  expected_points_scale: number;
  /** Each rival strategy's band on the decided week; absent on documents from before the field. */
  strategies?: Partial<
    Record<RivalStrategy, { overlap_floor: number | null; overlap_ceiling: number | null }>
  >;
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

/** The rival a strategy is played against: their public eleven and captain, from their entry document. */
export interface DeviceRival {
  entry_id: number;
  starting_xi: number[];
  captain: number;
}

export type DeviceRivalPlanKind = "within_free_transfers" | "with_hits";

/** What a rival strategy publishes beyond the plan itself, as the server names it. */
export interface DeviceRivalFields {
  mode: RivalStrategy;
  rival_entry_id: number;
  expected_points_cost: number;
  expected_points_cost_ceiling: number;
  overlap_count: number;
  transfer_cap: number;
  overlap_target: number;
  overlap_applied: number;
  plan_kind: DeviceRivalPlanKind;
  alternative_plan: {
    kind: DeviceRivalPlanKind;
    overlap_applied: number;
    transfer_hit_points: number;
    expected_points_cost: number;
    expected_points_cost_ceiling: number;
  } | null;
  expected_gap_vs_rival: number;
  captain_agreement: boolean;
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
  /**
   * The swaps as the advice prints them, paired by position in id order. Each row's gain
   * is what the basis moved by when that swap was applied after the rows above it, so
   * the rows add up to `expected_gain_vs_hold` exactly; null on every row when the chain
   * does not end at the eleven the plan fields.
   */
  moves: DevicePlanMove[];
  expected_gain_vs_hold: number | null;
  /** The chip the week was solved with, or null; every total above is on its basis. */
  chip: DeviceChip | null;
  /**
   * With a chip: the chip week's points net of hits above the member's own no-chip plan,
   * net of its hits. Absent without a chip.
   */
  gain_vs_no_chip?: number;
  /** With a rival strategy: the band's account. Absent for the plain plan and a chip. */
  rival?: DeviceRivalFields;
  seconds: number;
}

export interface DevicePlanMove {
  out: number | null;
  in: number | null;
  gain: number | null;
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

function isBands(value: unknown): boolean {
  if (!record(value)) return false;
  return Object.values(value).every(
    (band) =>
      record(band) &&
      (band.overlap_floor === null || finite(band.overlap_floor)) &&
      (band.overlap_ceiling === null || finite(band.overlap_ceiling)),
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
    (rules.hit_charged_scaled === undefined || finite(rules.hit_charged_scaled)) &&
    (rules.strategies === undefined || isBands(rules.strategies)) &&
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
