import { isDecisionInformation, isOfficialInformation } from "./informationFacts";
import { isOfficialInjuryFacts } from "./officialInjuryFacts";
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
    version: oneOf(
      "football_team_share_v1",
      "football_contextual_v3",
      "football_joint_role_minutes_v1",
    ),
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

function closedFields(
  value: unknown,
  required: Record<string, Predicate>,
  optional: Record<string, Predicate> = {},
): boolean {
  return (
    record(value) &&
    Object.keys(value).every(
      (key) => Object.hasOwn(required, key) || Object.hasOwn(optional, key),
    ) &&
    fields(value, required, optional)
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
const lineupExpectation: Predicate = (value) =>
  record(value) &&
  Object.keys(value).length === 8 &&
  fields(value, {
    version: oneOf("expected_lineup_v1"),
    expected_net_points: finite,
    starting_points: finite,
    autosub_points: finite,
    captain_bonus_points: finite,
    vice_bonus_points: finite,
    bench_boost_points: finite,
    assumptions: array(text),
  });
const lineup =
  (member: Predicate): Predicate =>
  (value) =>
    record(value) &&
    Object.keys(value).length === 4 &&
    fields(value, {
      starting_xi: (players) =>
        Array.isArray(players) && players.length === 11 && players.every(member),
      captain: member,
      vice_captain: member,
      bench: (players) => Array.isArray(players) && players.length === 4 && players.every(member),
    });
const planWeek: Predicate = (value) =>
  fields(
    value,
    {
      gameweek: identity,
      transfers_in: array(player),
      transfers_out: array(player),
      transfer_hit_points: finite,
      chip,
      free_transfers_before: integer,
      free_transfers_after: integer,
      expected_points: finite,
    },
    { lineup_expectation: lineupExpectation, lineup: lineup(player) },
  );
const participationEvidence: Predicate = (value) =>
  record(value) &&
  Object.keys(value).length === (value.statement_outcomes === undefined ? 8 : 9) &&
  fields(
    value,
    {
      version: oneOf("football_participation_evidence_v1"),
      as_of: nullable(text),
      gameweek: nullable(identity),
      applied_player_count: integer,
      unapplied_statement_count: integer,
      captured_percentage_count: integer,
      manager_statement_count: integer,
      assumptions: array(text),
    },
    {
      statement_outcomes: array(
        (row) =>
          record(row) &&
          Object.keys(row).length === 6 &&
          fields(row, {
            player_id: identity,
            disposition: text,
            applied: oneOf(true, false),
            reason: text,
            source_url: nullable(text),
            source_published_at: nullable(text),
          }),
      ),
    },
  );
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
    version: oneOf(
      "model_opportunity_reservation_v1",
      "model_opportunity_reservation_v2",
      "dated_joint_opportunity_v3",
    ),
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

const probability: Predicate = (value) => finite(value) && Number(value) >= 0 && Number(value) <= 1;
const nonnegative: Predicate = (value) => finite(value) && Number(value) >= 0;
const rolePointComponents: Predicate = (value) =>
  closedFields(value, {
    appearance: nonnegative,
    goals: nonnegative,
    assists: nonnegative,
    clean_sheet: nonnegative,
    defcon: nonnegative,
    other: finite,
    clipping: nonnegative,
    total: nonnegative,
  });
const roleForecast: Predicate = (value) =>
  closedFields(value, {
    version: oneOf("football_role_forecast_v1"),
    model_version: oneOf("football_joint_role_minutes_v1"),
    calibration: oneOf("not_independently_verified"),
    scope: oneOf("current_gameweek_fixtures"),
    rows: array((row) =>
      closedFields(
        row,
        {
          player_id: identity,
          name: text,
          fixture_id: identity,
          gameweek: identity,
          kickoff: text,
          status: oneOf("fitted_known_start_labels", "unavailable_no_known_start_labels"),
          expected_minutes: (v) => finite(v) && Number(v) >= 0 && Number(v) <= 120,
          captured_eligibility_multiplier: probability,
          news_applied: oneOf(true, false),
        },
        { point_components: rolePointComponents },
      ),
    ),
  });

const policyComparison: Predicate = (value) =>
  closedFields(value, {
    version: oneOf("completed_policy_comparison_v1"),
    basis: oneOf("expected_own_points"),
    baseline_index: integer,
    scenario_ids: array(text),
    news_arrival_probability: oneOf(null),
    scope: oneOf("supplied_conditional_scenarios_only"),
    terminal_resource_value_added: oneOf(false),
    candidates: array((row) =>
      closedFields(row, {
        index: integer,
        action_kind: oneOf("hold", "move", "chip"),
        first_state: (state) =>
          closedFields(state, { bank_tenths: integer, free_transfers: integer }),
        scenario_min: finite,
        scenario_max: finite,
        branch_gaps_vs_baseline: (gaps) => record(gaps) && Object.values(gaps).every(finite),
        minimum_gap_vs_baseline: finite,
        maximum_gap_vs_baseline: finite,
        dominates_baseline: oneOf(true, false),
        dominated_by: array(integer),
      }),
    ),
  });

const informationReview: Predicate = (value) =>
  fields(
    value,
    {
      version: oneOf("football_information_review_v1"),
      status: oneOf("compared", "baseline_retained"),
      reason: text,
      source_snapshot_id: text,
      captured_at_utc: text,
      player_name: nullable(text),
      source_playing_chance_percent: oneOf(null, 25, 50, 75),
      information_gameweek: nullable(identity),
      candidates: array((candidate) =>
        fields(
          candidate,
          {
            selected: oneOf(true, false),
            baseline: oneOf(true, false),
            transfers_in: array(text),
            transfers_out: array(text),
            chip,
            expected_net_points: nullable(finite),
            branches: array((branch) =>
              fields(branch, {
                state: oneOf("eligible", "unavailable"),
                expected_net_points: nullable(finite),
                hit_points: finite,
                weeks: array((week) =>
                  fields(
                    week,
                    {
                      gameweek: identity,
                      transfers_in: array(text),
                      transfers_out: array(text),
                      chip,
                      bank_tenths: integer,
                      free_transfers: integer,
                    },
                    { lineup: lineup(text) },
                  ),
                ),
              }),
            ),
          },
          {
            first_lineup: lineup(text),
          },
        ),
      ),
    },
    { comparison: policyComparison },
  );

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
      information_review: informationReview,
      role_forecast: roleForecast,
      lineup_expectation: lineupExpectation,
      participation_evidence: participationEvidence,
      official_information: isOfficialInformation,
      official_injuries: isOfficialInjuryFacts,
      decision_information: isDecisionInformation,
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
