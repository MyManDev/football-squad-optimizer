/** Runtime counterpart of docs/contracts/advice_read_v1.schema.json. */
import { checkedPreferences } from "./decisionPreferences";

type Predicate = (value: unknown) => boolean;
const record = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);
const text: Predicate = (value) => typeof value === "string";
const finite: Predicate = (value) => typeof value === "number" && Number.isFinite(value);
const integer: Predicate = (value) => Number.isSafeInteger(value) && Number(value) >= 0;
const identity: Predicate = (value) => integer(value) && Number(value) > 0;
const oneOf =
  (...values: unknown[]): Predicate =>
  (value) =>
    values.includes(value);
const nullable =
  (check: Predicate): Predicate =>
  (value) =>
    value === null || check(value);
const array =
  (check: Predicate): Predicate =>
  (value) =>
    Array.isArray(value) && value.every(check);

const predictionModel: Predicate = (value) =>
  record(value) &&
  Object.keys(value).length === 4 &&
  fields(value, {
    id: oneOf("football"),
    version: oneOf("football_team_share_v1", "football_contextual_v3"),
    experimental: oneOf(true),
    fingerprint: (digest) => typeof digest === "string" && /^[a-f0-9]{64}$/.test(digest),
  });

const preferences: Predicate = (value) => {
  if (!record(value)) return false;
  try {
    checkedPreferences(value);
    return true;
  } catch {
    return false;
  }
};

function fields(
  value: unknown,
  required: Record<string, Predicate>,
  optional: Record<string, Predicate> = {},
): boolean {
  return (
    record(value) &&
    Object.entries(required).every(([key, check]) => check(value[key])) &&
    Object.entries(optional).every(([key, check]) => !(key in value) || check(value[key]))
  );
}

const player: Predicate = (value) =>
  fields(
    value,
    {
      player_id: identity,
      name: text,
      short_name: text,
      team: text,
      position: oneOf("GK", "DEF", "MID", "FWD"),
    },
    { expected_points: finite },
  );
const chip = oneOf(null, "bboost", "3xc", "wildcard", "freehit");
const planKind = oneOf("within_free_transfers", "with_hits");
const move: Predicate = (value) =>
  fields(value, {
    move_id: text,
    player_out: nullable(player),
    player_in: nullable(player),
    expected_points_delta: nullable(finite),
    reason_code: oneOf(
      "window_value",
      "mode_tradeoff",
      "points_gain",
      "manager_word",
      "top100_preference",
    ),
  });
const planWeek: Predicate = (value) =>
  fields(value, {
    gameweek: identity,
    transfers_in: array(player),
    transfers_out: array(player),
    transfer_hit_points: finite,
    chip,
    free_transfers_before: integer,
    free_transfers_after: integer,
    expected_points: finite,
  });
const alternative: Predicate = (value) =>
  fields(
    value,
    {
      kind: planKind,
      overlap_applied: finite,
      transfer_hit_points: nullable(finite),
      expected_points_cost: finite,
    },
    { expected_points_cost_ceiling: finite },
  );

const evidence: Predicate = (value) =>
  fields(value, {
    kind: oneOf("managers_word"),
    source_kind: text,
    clubs_covered: array(text),
    applied: array(record),
  });

const top100: Predicate = (value) =>
  fields(
    value,
    {
      weight: oneOf(5, 10, 20, 30, 40, 50),
      changed: oneOf(true, false),
      price_basis: text,
    },
    {
      cohort_snapshot_id: text,
      picks_snapshot_id: text,
      table_sha256: text,
      picks_gameweek: identity,
    },
  );

const chipChoice: Predicate = (value) =>
  fields(
    value,
    {
      chip: oneOf("bboost", "3xc", "wildcard", "freehit"),
      gain_vs_no_chip: finite,
      basis: text,
    },
    { windows_left: record },
  );

const chipStrategy: Predicate = (value) =>
  fields(value, {
    version: oneOf("model_opportunity_reservation_v1"),
    mode: oneOf("auto", "manual"),
    requested_chip: oneOf("auto", "bboost", "3xc", "wildcard", "freehit"),
    selected_chip: chip,
    top100_weight: oneOf(0, 5, 10, 20, 30, 40, 50),
    objective_gap: nullable(finite),
    objective_basis: oneOf("selection_utility_with_chip_reserve"),
    experimental: oneOf(true, false),
    reservations: array((row) =>
      fields(row, {
        chip: oneOf("bboost", "3xc", "wildcard", "freehit"),
        first_gameweek: identity,
        last_gameweek: identity,
        remaining_opportunities: integer,
        holding_value: finite,
        sample_min: finite,
        sample_max: finite,
      }),
    ),
    limits: array(text),
  });

export function isAdvicePayload(value: unknown): boolean {
  return fields(
    value,
    {
      league_id: identity,
      season: text,
      gameweek: identity,
      entry_id: identity,
      mode: text,
      window: oneOf(1, 3, 5),
      moves: array(move),
      data_quality: oneOf("complete", "partial", "empty"),
      missing_fields: array(text),
    },
    {
      source_snapshot_id: nullable(text),
      prediction_model: predictionModel,
      preferences,
      preferences_scope: oneOf("all_selected_weeks"),
      selection_top100_weight: oneOf(0, 5, 10, 20, 30, 40, 50),
      rival_entry_id: identity,
      rival_label: nullable(text),
      transfer_hit_points: finite,
      expected_gain_vs_hold: nullable(finite),
      expected_points_cost: finite,
      expected_points_cost_ceiling: finite,
      overlap_count: finite,
      expected_gap_vs_rival: finite,
      transfer_cap: finite,
      overlap_target: finite,
      overlap_applied: finite,
      captain_agreement: oneOf(true, false),
      solver_status: nullable(text),
      wall_clock_stopped_the_search: nullable(oneOf(true, false)),
      control_solver_status: nullable(text),
      optimality_gap: nullable(finite),
      control_optimality_gap: nullable(finite),
      evidence,
      top100,
      chip_choice: chipChoice,
      chip_strategy: chipStrategy,
      expected_own_points: nullable(finite),
      captain: nullable(player),
      vice_captain: nullable(player),
      starting_xi: nullable(array(player)),
      bench: nullable(array(player)),
      chip,
      plan_weeks: nullable(array(planWeek)),
      stated_limits: nullable(array(text)),
      squad_basis: text,
      plan_kind: planKind,
      alternative_plan: nullable(alternative),
    },
  );
}
