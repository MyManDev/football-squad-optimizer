/** Runtime counterpart of docs/contracts/advice_read_v1.schema.json. */
import type { MemberChipRecommendations } from "../types";
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
    expected_points_delta: finite,
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

const chipRecommendationShape: Predicate = (value) =>
  fields(value, {
    contract_version: oneOf("member_chip_recommendations_v1"),
    planning_policy_id: text,
    gameweeks: array(identity),
    control_solver_status: text,
    control_optimality_gap: nullable(finite),
    comparisons: array((row) =>
      fields(row, {
        chip: oneOf("bboost", "3xc", "wildcard", "freehit"),
        available_from_gameweek: identity,
        last_usable_gameweek: identity,
        remaining: identity,
        action: oneOf("play", "hold"),
        gameweek: nullable(identity),
        expected_points_gain: nullable(finite),
        reason: oneOf("window_gain", "no_positive_gain", "outside_horizon"),
        solver_status: nullable(text),
        optimality_gap: nullable(finite),
        decision: nullable((decision) =>
          fields(decision, {
            gameweek: identity,
            captain: player,
            vice_captain: player,
            starting_xi: array(player),
            bench: array(player),
            chip,
            expected_own_points: finite,
            transfer_hit_points: finite,
          }),
        ),
      }),
    ),
  });

const chipRecommendations: Predicate = (value) => {
  if (!chipRecommendationShape(value)) return false;
  const block = value as MemberChipRecommendations;
  const weeks = block.gameweeks;
  const solved = (status: string | null) => status === "OPTIMAL" || status === "FEASIBLE";
  const gap = (value: number | null) => value === null || value >= 0;
  if (
    ![1, 3, 5].includes(weeks.length) ||
    !weeks.every((week, i) => week === weeks[0] + i) ||
    !block.planning_policy_id.trim() ||
    !solved(block.control_solver_status) ||
    !gap(block.control_optimality_gap)
  )
    return false;
  const seen = new Map<string, [number, number][]>();
  return block.comparisons.every((row) => {
    const start = row.available_from_gameweek,
      stop = row.last_usable_gameweek;
    const prior = seen.get(row.chip) ?? [];
    if (
      start > stop ||
      prior.some(([low, high]) => !(stop < low || start > high)) ||
      !gap(row.optimality_gap)
    )
      return false;
    seen.set(row.chip, [...prior, [start, stop]]);
    const available = weeks.some((week) => start <= week && week <= stop);
    if (row.action === "hold") {
      if (row.gameweek !== null || row.decision !== null) return false;
      return row.reason === "outside_horizon"
        ? !available &&
            row.expected_points_gain === null &&
            row.solver_status === null &&
            row.optimality_gap === null
        : row.reason === "no_positive_gain" &&
            available &&
            solved(row.solver_status) &&
            (row.expected_points_gain === null || row.expected_points_gain <= 0);
    }
    const decision = row.decision;
    if (
      row.gameweek === null ||
      !weeks.includes(row.gameweek) ||
      row.gameweek < start ||
      row.gameweek > stop ||
      row.reason !== "window_gain" ||
      row.expected_points_gain === null ||
      row.expected_points_gain <= 0 ||
      !solved(row.solver_status) ||
      !decision ||
      decision.gameweek !== row.gameweek ||
      decision.chip !== row.chip ||
      decision.transfer_hit_points < 0 ||
      decision.starting_xi.length !== 11 ||
      decision.bench.length !== 4
    )
      return false;
    const players = [...decision.starting_xi, ...decision.bench];
    if (
      new Set(players.map((player) => player.player_id)).size !== 15 ||
      decision.captain.player_id === decision.vice_captain.player_id
    )
      return false;
    const armbands = [decision.captain, decision.vice_captain];
    if (
      !armbands.every((armband) => {
        const starter = decision.starting_xi.find(
          (player) => player.player_id === armband.player_id,
        );
        return (
          starter &&
          Object.entries(starter).every(
            ([key, value]) => value === armband[key as keyof typeof armband],
          )
        );
      })
    )
      return false;
    return Object.entries({ GK: [2, 1, 1], DEF: [5, 3, 5], MID: [5, 2, 5], FWD: [3, 1, 3] }).every(
      ([position, [total, min, max]]) => {
        const starters = decision.starting_xi.filter(
          (player) => player.position === position,
        ).length;
        return (
          players.filter((player) => player.position === position).length === total &&
          starters >= min &&
          starters <= max
        );
      },
    );
  });
};

export function isAdvicePayload(value: unknown): boolean {
  const valid = fields(
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
      chip_recommendations: chipRecommendations,
      plan_weeks: nullable(array(planWeek)),
      stated_limits: nullable(array(text)),
      plan_kind: planKind,
      alternative_plan: nullable(alternative),
    },
  );
  if (!valid || !record(value)) return false;
  const block = value.chip_recommendations as MemberChipRecommendations | undefined;
  return (
    !block ||
    (block.gameweeks.length === value.window &&
      block.gameweeks.every((week, index) => week === Number(value.gameweek) + index))
  );
}
