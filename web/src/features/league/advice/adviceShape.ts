/** Runtime counterpart of docs/contracts/advice_read_v1.schema.json. */
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
    reason_code: oneOf("window_value", "mode_tradeoff", "points_gain"),
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

const comparisonFields: Record<string, Predicate> = {
  policy_id: oneOf("first_week_rival_horizon_v1"),
  rival_entry_id: identity,
  rival_gameweek: identity,
  overlap_scope: oneOf("first_week_squad_vs_captured_rival_xi"),
  overlap_minimum: nullable((v) => integer(v) && Number(v) <= 11),
  overlap_maximum: nullable((v) => integer(v) && Number(v) <= 11),
  overlap_actual: (v) => integer(v) && Number(v) <= 11,
  first_week_net_points: finite,
  control_first_week_net_points: finite,
  total_net_points: finite,
  control_total_net_points: finite,
  net_points_difference: finite,
  solver_status: oneOf("OPTIMAL", "FEASIBLE"),
  control_solver_status: oneOf("OPTIMAL", "FEASIBLE"),
  optimality_gap: nullable(finite),
  control_optimality_gap: nullable(finite),
};

function validWindowComparison(value: unknown): boolean {
  if (!record(value)) return false;
  const c = "window_comparison" in value ? value.window_comparison : undefined;
  const multiRival =
    [3, 5].includes(Number(value.window)) &&
    ["ortak-koru", "fark-yarat"].includes(String(value.mode));
  if (c === undefined && !multiRival) return true;
  if (
    !multiRival ||
    !record(c) ||
    !fields(c, comparisonFields) ||
    Object.keys(c).some((k) => !Object.hasOwn(comparisonFields, k))
  )
    return false;
  const weeks = value.plan_weeks;
  if (
    !Array.isArray(weeks) ||
    weeks.length !== value.window ||
    weeks.some((w, i) => !record(w) || w.gameweek !== Number(value.gameweek) + i)
  )
    return false;
  const minimum = c.overlap_minimum === null ? null : Number(c.overlap_minimum);
  const maximum = c.overlap_maximum === null ? null : Number(c.overlap_maximum);
  if (
    c.rival_entry_id !== value.rival_entry_id ||
    c.rival_entry_id === value.entry_id ||
    c.rival_gameweek !== Number(value.gameweek) - 1 ||
    (value.mode === "ortak-koru"
      ? minimum === null || maximum !== null
      : maximum === null || minimum !== null) ||
    (minimum !== null && Number(c.overlap_actual) < minimum) ||
    (maximum !== null && Number(c.overlap_actual) > maximum) ||
    c.solver_status !== value.solver_status ||
    c.optimality_gap !== value.optimality_gap
  )
    return false;
  const nets = weeks.map((w) => Number(w.expected_points) - Number(w.transfer_hit_points));
  const total = nets.reduce((sum, n) => sum + n, 0);
  const close = (a: unknown, b: number) =>
    Math.abs(Number(a) - b) <= Math.max(1e-8, 1e-9 * Math.max(Math.abs(Number(a)), Math.abs(b)));
  return (
    finite(value.expected_points_cost) &&
    finite(value.expected_points_cost_ceiling) &&
    close(value.expected_points_cost, Math.max(0, Number(c.control_total_net_points) - total)) &&
    Number(value.expected_points_cost_ceiling) >= Number(value.expected_points_cost) &&
    close(c.first_week_net_points, nets[0]!) &&
    close(c.total_net_points, total) &&
    close(c.net_points_difference, Number(c.control_total_net_points) - total)
  );
}

export function isAdvicePayload(value: unknown): boolean {
  return (
    validWindowComparison(value) &&
    fields(
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
        control_solver_status: nullable(text),
        optimality_gap: nullable(finite),
        control_optimality_gap: nullable(finite),
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
    )
  );
}
