/**
 * The two published documents a member's device needs to solve its own one-week plan,
 * and the answer the solve returns. Shapes mirror `squadopt.application.device_plan`.
 */

export const DEVICE_PLAN_CONTRACT_VERSION = "league_device_plan_v1";
/**
 * The capture's own table (#981 step 1): the same document once per capture, under
 * `data/device/<capture>/`, with no league in it and four fields more.
 */
export const DEVICE_PLAN_TABLE_CONTRACT_VERSION = "league_device_plan_v2";

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
  /** With `rules.top100`: how many of the cohort started him last gameweek. */
  top100_count?: number;
  /** With `rules.top100`: his weighted points on the integer scale, by weight as text. */
  top100_scaled?: Record<string, number>;
  /** On the capture's table: the game's per-season element id. */
  element_id?: number;
  /** On the capture's table: his price at the season's first deadline, in tenths. */
  start_tenths?: number;
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
  /** The Top 100 influence's inputs, where the week has them. */
  top100?: {
    weights: number[];
    cohort_size: number;
    cohort_snapshot_id: string;
    picks_snapshot_id: string;
    table_sha256: string;
    picks_gameweek: number;
  };
  /** On the capture's table: the season's chip windows as the rules state them. */
  chips?: unknown[];
  /** On the capture's table: the game's cap on transfers in one week, or null. */
  transfers_cap?: number | null;
}

/**
 * The capture's table in solver order, and the rules as numbers: the league tree's copy
 * (`device-plan.json`, v1, naming its league) or the capture's own table (v2, naming none).
 */
export interface DevicePlanDocument {
  contract_version: typeof DEVICE_PLAN_CONTRACT_VERSION | typeof DEVICE_PLAN_TABLE_CONTRACT_VERSION;
  /** The league the tree's copy belongs to; absent on the capture's table. */
  league_id?: number;
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

/** What a Top 100 weight publishes beyond the plan: the price on base points and each row's reason. */
export interface DeviceTop100Fields {
  weight: number;
  /** Whether the weighted choice differs from the same strategy at zero in a move, the eleven or the captain. */
  changed: boolean;
  expected_points_cost: number;
  expected_points_cost_ceiling: number;
  /** One per move row, preserving the unweighted strategy's reason for a shared move. */
  reasons: Array<"points_gain" | "mode_tradeoff" | "top100_preference">;
}

/** One member's side of the problem, from `entries/<id>.json`. */
export interface DevicePlanEntry {
  held: number[];
  bank_tenths: number;
  free_transfers: number;
  /** Sale price of each held player, keyed by player id as text. */
  sell_tenths: Record<string, number>;
  /** The Top 100 weights the shared document carries; absent where the week has none. */
  top100_weights?: number[];
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
  /**
   * With chip gains asked for: each held chip's gain this week against this plain plan,
   * null where its solve was refused. Absent otherwise.
   */
  chip_gains?: Partial<Record<DeviceChip, number | null>>;
  /** With a rival strategy: the band's account. Absent for the plain plan and a chip. */
  rival?: DeviceRivalFields;
  /** With a Top 100 weight: its account. */
  top100?: DeviceTop100Fields;
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

function isPlayer(value: unknown, table: boolean): value is DevicePlanPlayer {
  if (!record(value)) return false;
  return (
    (!table || (finite(value.element_id) && finite(value.start_tenths))) &&
    finite(value.id) &&
    typeof value.name === "string" &&
    typeof value.short_name === "string" &&
    typeof value.team === "string" &&
    typeof value.position === "string" &&
    finite(value.buy_tenths) &&
    finite(value.expected_points) &&
    Array.isArray(value.coefficients) &&
    value.coefficients.length === 3 &&
    value.coefficients.every(finite) &&
    (value.top100_count === undefined || finite(value.top100_count)) &&
    (value.top100_scaled === undefined || numberMap(value.top100_scaled))
  );
}

function isTop100Rules(value: unknown): boolean {
  if (!record(value)) return false;
  return (
    Array.isArray(value.weights) &&
    value.weights.every(finite) &&
    finite(value.cohort_size) &&
    typeof value.cohort_snapshot_id === "string" &&
    typeof value.picks_snapshot_id === "string" &&
    typeof value.table_sha256 === "string" &&
    finite(value.picks_gameweek)
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

/**
 * The league tree's copy names its league; the capture's table names none, and carries
 * each player's element id and start price and the season's chip windows and transfer cap.
 */
export function isDevicePlanDocument(value: unknown): value is DevicePlanDocument {
  if (!record(value)) return false;
  const table = value.contract_version === DEVICE_PLAN_TABLE_CONTRACT_VERSION;
  if (!table && value.contract_version !== DEVICE_PLAN_CONTRACT_VERSION) return false;
  const rules = value.rules;
  if (!record(rules)) return false;
  return (
    (table
      ? value.league_id === undefined &&
        Array.isArray(rules.chips) &&
        (rules.transfers_cap === null || finite(rules.transfers_cap))
      : finite(value.league_id)) &&
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
    (rules.top100 === undefined || isTop100Rules(rules.top100)) &&
    finite(rules.expected_points_scale) &&
    rules.expected_points_scale > 0 &&
    Array.isArray(value.players) &&
    value.players.length > 0 &&
    value.players.every((player) => isPlayer(player, table))
  );
}

export function isDevicePlanEntry(value: unknown): value is DevicePlanEntry {
  if (!record(value)) return false;
  return (
    Array.isArray(value.held) &&
    value.held.every(finite) &&
    finite(value.bank_tenths) &&
    finite(value.free_transfers) &&
    numberMap(value.sell_tenths) &&
    (value.top100_weights === undefined ||
      (Array.isArray(value.top100_weights) && value.top100_weights.every(finite)))
  );
}
