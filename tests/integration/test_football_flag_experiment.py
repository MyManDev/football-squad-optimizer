"""Private captured flags reach learned minutes and independent legal squad scoring."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from math import exp, fsum, prod

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.football_flag_fixtures import (
    BENCH,
    DEADLINE_AT,
    DECISION_AT,
    FIT_CUTOFF,
    SEASON,
    STATE_MINUTES,
    STATE_PROBABILITIES,
    XI,
    case_inputs,
    case_week_documents,
    component_oracle,
    encoded,
    independent_lineup_oracle,
    native_case,
    parse_week_document,
    training_weeks,
    week_state_oracle,
)

from squadopt.application.football_flag_experiment import (
    RECEIPT_ATTR,
    compose_flag_experiment,
    native_basis_digest,
    plan_flag_fixed_fifteen,
)
from squadopt.data.errors import DataError
from squadopt.evaluation.models import EvaluationValidationError
from squadopt.features.football_flag_inputs import read_flag_week_source
from squadopt.prediction.football_flag_minutes import FlagMinutesModel


@pytest.fixture(scope="module")
def model():
    return FlagMinutesModel(
        training_weeks(),
        fit_cutoff=FIT_CUTOFF,
        target_season=SEASON,
        target_gameweeks=(6, 7),
    )


def compose(case, model=None, *, labels=None, weeks=None, **options):
    kwargs = dict(
        season=SEASON,
        gameweeks=case.gameweeks,
        decision_at=DECISION_AT,
        deadline_at=DEADLINE_AT,
        captured_availability=case.captured_availability,
        enabled=True,
    )
    kwargs.update(options)
    return compose_flag_experiment(
        case.components,
        case.weekly,
        case.roster,
        case.calendar,
        case.resource_bundle,
        (case_inputs(case, labels=labels) if weeks is None else weeks)
        if kwargs["enabled"] and not kwargs.get("control")
        else (),
        model,
        **kwargs,
    )


def plan(experiment, **options):
    return plan_flag_fixed_fifteen(
        experiment,
        tuple(range(1, 16)),
        XI,
        BENCH,
        13,
        8,
        gameweek=6,
        **options,
    )


def with_labels(case, labels):
    availability = {**case.captured_availability, **{p: label / 100 for p, label in labels.items()}}
    weekly = case.weekly.copy(deep=True)
    for index, row in weekly.iterrows():
        selected = case.components.loc[
            case.components.player_code.eq(row.player_id) & case.components.GW.eq(row.gameweek)
        ]
        a = availability[int(row.player_id)]
        weekly.at[index, "expected_points"] = a * fsum(selected.expected_points)
        weekly.at[index, "appearance_probability"] = a * (
            1 - prod(1 - q for q in selected.appearance_probability)
        )
    return replace(case, weekly=weekly, captured_availability=availability)


def recompute_native_scores(case):
    for index, row in case.components.iterrows():
        values = component_oracle(row, STATE_PROBABILITIES, STATE_MINUTES)
        for name, value in values.items():
            case.components.at[index, name] = value
    return with_labels(case, {})


def independent_hurdle(week, metadata):
    """Construct published categorical features without importing model transforms."""
    numeric = (week.news_age_hours, week.capture_age_hours, len(week.fixtures))
    numeric_names = ("news_age_hours", "capture_age_hours", "fixture_count")
    fields = {
        "intercept": 1.0,
        "history_covered": float(week.history_covered),
        "label_changed": float(week.label_changed or False),
        "missing:label_changed": float(week.label_changed is None),
    }
    for name in metadata.feature_names:
        if ":" not in name:
            continue
        family, value = name.split(":", 1)
        if family in ("position", "status", "label", "news"):
            actual = getattr(week, "news_state" if family == "news" else family)
            fields[name] = float(str(actual) == value)
    for name, value, mean, scale in zip(
        numeric_names, numeric, metadata.numeric_means, metadata.numeric_scales, strict=True
    ):
        fields[f"missing:{name}"] = float(value is None)
        fields[f"standardized:{name}"] = 0.0 if value is None else (value - mean) / scale
    absent = prod(f.probabilities[0] for f in week.fixtures)
    logit = (
        np.log(1 - absent)
        - np.log(absent)
        + fsum(
            fields[name] * beta
            for name, beta in zip(metadata.feature_names, metadata.hurdle_coefficients, strict=True)
        )
    )
    return float(1 / (1 + exp(-logit)))


def oracle_components(case, predictions):
    rows = []
    by_player_week = {(p.week.player_code, p.week.gameweek): p for p in predictions}
    for native in case.components.to_dict("records"):
        prediction = by_player_week[int(native["player_code"]), int(native["GW"])]
        fixture_index = next(
            i
            for i, fixture in enumerate(prediction.week.fixtures)
            if fixture.fixture == native["fixture"]
        )
        _, marginals = week_state_oracle(
            prediction.states,
            prediction.probabilities,
            tuple(fixture.minutes for fixture in prediction.week.fixtures),
        )
        row = dict(native)
        row.update(
            component_oracle(
                row, marginals[fixture_index], prediction.week.fixtures[fixture_index].minutes
            )
        )
        row["_oracle_probabilities"] = marginals[fixture_index]
        row["_oracle_minutes"] = prediction.week.fixtures[fixture_index].minutes
        rows.append(row)
    output = pd.DataFrame(rows, index=case.components.index)
    original = case.components.set_index(["fixture", "player_code"])
    for _, side in output.groupby(["fixture", "club"]):
        before = original.loc[
            [(int(row.fixture), int(row.player_code)) for row in side.itertuples()]
        ]
        ratio = side.expected_minutes.to_numpy(float) / before.expected_minutes.to_numpy(float)
        for count in ("goals", "assists"):
            weights = before[count + "_share"].to_numpy(float) * ratio
            shares = weights / fsum(weights)
            output.loc[side.index, count + "_share"] = shares
            output.loc[side.index, count] = fsum(before[count]) * shares
    for index, row in output.iterrows():
        actual = component_oracle(row, row["_oracle_probabilities"], row["_oracle_minutes"])
        for name, value in actual.items():
            output.at[index, name] = value
    return output


@pytest.mark.parametrize("double", [False, True])
def test_raw_sources_fit_then_fixture_and_week_match_independent_state_oracle(model, double):
    case = native_case(double=double, residuals={66: -20.0})
    saved = deepcopy(case)
    weeks = case_inputs(case)
    predictions = tuple(model.predict(week) for week in weeks)
    result = compose(case, model)
    expected = oracle_components(case, predictions)
    columns = (
        "expected_minutes",
        "appearance_probability",
        "p60",
        "start_probability",
        "cameo_probability",
        "clean_sheet_probability",
        "defcon_probability",
        "goals",
        "assists",
        "goals_share",
        "assists_share",
        "raw_expected_points",
        "expected_points",
    )
    np.testing.assert_allclose(
        result.components[list(columns)], expected[list(columns)], rtol=1e-11, atol=1e-11
    )
    for prediction in predictions:
        row = result.weekly.loc[
            result.weekly.player_id.eq(prediction.week.player_code)
            & result.weekly.gameweek.eq(prediction.week.gameweek)
        ].iloc[0]
        q, _ = week_state_oracle(
            prediction.states,
            prediction.probabilities,
            tuple(f.minutes for f in prediction.week.fixtures),
        )
        assert row.appearance_probability == pytest.approx(q, abs=1e-12)
        fixture_rows = expected.loc[
            expected.player_code.eq(prediction.week.player_code)
            & expected.GW.eq(prediction.week.gameweek)
        ]
        assert row.expected_points == pytest.approx(fsum(fixture_rows.expected_points), abs=1e-11)
    player = result.weekly.loc[result.weekly.player_id.eq(3)].iloc[0]
    prediction = next(p for p in predictions if p.week.player_code == 3)
    assert player.appearance_probability != pytest.approx(0.75 * prediction.weekly_appearance)
    assert (
        result.components.loc[result.components.player_code.eq(66), "raw_expected_points"]
        .lt(0)
        .all()
    )
    assert (
        result.components.loc[result.components.player_code.eq(66), "expected_points"].eq(0).all()
    )
    for name in ("components", "weekly", "roster", "calendar"):
        assert_frame_equal(getattr(case, name), getattr(saved, name), check_exact=True)
    for name in ("components", "weekly", "roster"):
        for key, value in getattr(case, name).attrs.items():
            assert getattr(result, name).attrs[key] == value
    assert case.resource_bundle == saved.resource_bundle


def test_goalkeeper_goal_coefficient_and_nonlinear_cs_do_not_use_mean_minutes(model):
    case = native_case()
    result = compose(case, model)
    keeper = result.components.loc[result.components.player_code.eq(1)].iloc[0]
    raw_without_goals = keeper.raw_expected_points - 10 * keeper.goals
    assert raw_without_goals == pytest.approx(
        keeper.appearance_probability
        + keeper.p60
        + 3 * keeper.assists
        + 4 * keeper.clean_sheet_probability
        + keeper.appearance_probability * keeper.residual_if_appearance,
    )
    row = result.components.loc[result.components.player_code.eq(3)].iloc[0]
    mean_cs = row.p60 * exp(-row.opponent_goal_rate * row.expected_minutes / 90)
    assert abs(row.clean_sheet_probability - mean_cs) > 1e-5


@pytest.mark.parametrize("mode", ["disabled", "control"])
def test_exact_legacy_control_keeps_supplied_values_resources_and_metadata(mode):
    case = native_case(double=True)
    result = compose(case, enabled=mode != "disabled", control=mode == "control")
    for name in ("components", "weekly"):
        actual = getattr(result, name).copy(deep=True)
        actual.attrs.pop(RECEIPT_ATTR)
        assert_frame_equal(actual, getattr(case, name), check_exact=True)
    assert_frame_equal(result.roster, case.roster, check_exact=True)
    assert json.loads(result.resource_bundle_json) == case.resource_bundle
    assert json.loads(result.receipt_json)["replacement_scope"] == "legacy_control"


@pytest.mark.parametrize("mode", ["disabled", "control"])
def test_zero_coefficient_switch_refuses_outside_the_learned_arm(model, mode):
    with pytest.raises(ValueError, match="zero-coefficient"):
        compose(
            native_case(),
            model,
            enabled=mode != "disabled",
            control=mode == "control",
            zero_coefficients=True,
        )


def test_zero_coefficient_ablation_is_unflagged_native_law_not_legacy_rule(model):
    case = native_case(double=True)
    result = compose(case, model, zero_coefficients=True)
    old = case.weekly.loc[case.weekly.player_id.eq(3)].iloc[0]
    row = result.weekly.loc[result.weekly.player_id.eq(3)].iloc[0]
    assert old.appearance_probability == pytest.approx(0.75 * 0.99)
    assert row.appearance_probability == pytest.approx(0.99)
    assert row.expected_points == pytest.approx(old.expected_points / 0.75)
    assert row.appearance_probability != old.appearance_probability
    assert json.loads(result.receipt_json)["zero_coefficients"] is True


def test_categorical_labels_have_independent_learned_appearance_and_role_effects(model):
    case = native_case()
    predictions = {
        label: model.predict(
            next(week for week in case_inputs(case, labels={3: label}) if week.player_code == 3)
        )
        for label in (0, 25, 50, 75)
    }
    assert predictions[25].weekly_appearance > predictions[50].weekly_appearance
    assert predictions[75].weekly_appearance > predictions[0].weekly_appearance
    assert len({round(p.weekly_appearance, 8) for p in predictions.values()}) == 4
    conditional_minutes = {
        label: fsum(
            prob * minutes
            for prob, minutes in zip(
                prediction.fixture_probabilities[0],
                prediction.week.fixtures[0].minutes,
                strict=True,
            )
        )
        / prediction.weekly_appearance
        for label, prediction in predictions.items()
    }
    assert conditional_minutes[25] < conditional_minutes[50]
    assert predictions[75].week.label == 75


def test_dgw_uses_joint_week_appearance_and_preserves_complete_club_totals(model):
    case = native_case(double=True)
    result = compose(case, model)
    player = result.components.loc[result.components.player_code.eq(3)]
    independent_union = 1 - prod(1 - q for q in player.appearance_probability)
    joint_q = result.weekly.loc[result.weekly.player_id.eq(3), "appearance_probability"].iloc[0]
    assert abs(joint_q - independent_union) > 1e-5
    for count in ("goals", "assists"):
        before = case.components.groupby(["fixture", "club"])[count].sum()
        after = result.components.groupby(["fixture", "club"])[count].sum()
        np.testing.assert_allclose(after, before, rtol=0, atol=1e-12)
    assert set(result.components.player_code) == set(case.roster.player_id)


def test_two_week_composition_binds_each_week_and_plans_only_covered_weeks(model):
    case = native_case(extra_week=True)
    later = case.components.GW.eq(7) & case.components.player_code.eq(3)
    case.components.loc[later, "residual_if_appearance"] = -4.0
    case = recompute_native_scores(case)
    result = compose(case, model)
    predictions = {
        (week.player_code, week.gameweek): model.predict(week) for week in case_inputs(case)
    }
    assert set(result.weekly.gameweek) == {6, 7}
    for row in result.weekly.itertuples():
        fixtures = result.components.loc[
            result.components.player_code.eq(row.player_id) & result.components.GW.eq(row.gameweek)
        ]
        assert row.expected_points == pytest.approx(fsum(fixtures.expected_points), abs=1e-12)
        assert row.appearance_probability == pytest.approx(
            predictions[row.player_id, row.gameweek].weekly_appearance, abs=1e-15
        )
    focal = result.weekly.loc[result.weekly.player_id.eq(3)].set_index("gameweek")
    assert focal.at[6, "expected_points"] > focal.at[7, "expected_points"]
    assert json.loads(result.receipt_json)["gameweeks"] == [6, 7]
    for gameweek in (6, 7):
        decision = plan_flag_fixed_fifteen(
            result, tuple(range(1, 16)), XI, BENCH, 13, 8, gameweek=gameweek
        )
        squad = decision.squad.set_index("player_id")
        assert squad.at[3, "expected_points"] == focal.at[gameweek, "expected_points"]
    with pytest.raises(ValueError, match="does not cover"):
        plan_flag_fixed_fifteen(result, tuple(range(1, 16)), XI, BENCH, 13, 8, gameweek=8)


def test_learned_composition_refuses_certain_native_appearance_without_epsilon(model):
    case = native_case(uncertain_players=[p for p in range(1, 67) if p != 3])
    focal = case.components.loc[case.components.player_code.eq(3)]
    assert focal.zero_probability.eq(0).all()
    for zero in (False, True):
        with pytest.raises(ValueError, match="interior"):
            compose(case, model, zero_coefficients=zero)
    control = compose(case, control=True)
    assert json.loads(control.receipt_json)["replacement_scope"] == "legacy_control"


def test_learned_blank_week_is_explicit_zero_with_complete_coverage(model):
    case = native_case(blank=True)
    result = compose(case, model)
    assert result.components.empty
    assert result.weekly.expected_points.eq(0).all()
    assert result.weekly.appearance_probability.eq(0).all()
    decision = plan(result)
    assert decision.search.best.expected_net_points == 0.0


@pytest.mark.parametrize("double", [False, True])
def test_weekly_hurdle_matches_independent_published_coefficient_oracle(model, double):
    case = native_case(double=double)
    week = next(week for week in case_inputs(case) if week.player_code == 3)
    expected = independent_hurdle(week, model.metadata)
    prediction = model.predict(week)
    assert prediction.weekly_appearance == pytest.approx(expected, abs=1e-12)
    if double:
        assert prediction.weekly_appearance != pytest.approx(expected**2)


def test_flag_changes_first_xi_captain_and_reserves_without_changing_fifteen(model):
    case = native_case(residuals={3: 6.0, 13: 4.0})
    low = compose(with_labels(case, {3: 0, 13: 0, 6: 0}), model)
    high = compose(with_labels(case, {3: 100, 13: 100, 6: 100}), model)
    low_plan, high_plan = plan(low), plan(high)
    assert low_plan.search.best.starting_xi != high_plan.search.best.starting_xi
    assert low_plan.search.best.captain_id != high_plan.search.best.captain_id
    assert low_plan.search.best.ordered_bench != high_plan.search.best.ordered_bench
    for decision in (low_plan, high_plan):
        assert set(decision.squad.player_id) == set(range(1, 16))
        assert decision.squad.groupby("team_id").size().max() <= 3
        assert len(decision.search.best.starting_xi) == 11
        assert len(decision.search.best.ordered_bench) == 4
        assert (
            decision.search.best.expected_net_points
            >= decision.search.incumbent.expected_net_points
        )
        original = case.roster.loc[case.roster.player_id.le(15)].reset_index(drop=True)
        assert_frame_equal(
            decision.squad[original.columns].reset_index(drop=True), original, check_exact=True
        )
        assert json.loads(decision.resource_bundle_json) == case.resource_bundle


def test_same_75_label_can_keep_a_starter_or_bench_a_weaker_fixture_forecast(model):
    favorable = native_case(residuals={3: 10.0})
    weaker = native_case(residuals={3: -4.0})
    weaker.components.loc[weaker.components.club.eq(3), "opponent_goal_rate"] = 6.0
    weaker.components.loc[weaker.components.club.eq(4), "team_goal_rate"] = 6.0
    weaker = recompute_native_scores(weaker)
    favorable_result = compose(favorable, model)
    weaker_result = compose(weaker, model)
    first, second = plan(favorable_result), plan(weaker_result)
    assert 3 in first.search.best.starting_xi
    assert 3 not in second.search.best.starting_xi
    assert 3 in second.search.best.ordered_bench
    first_q = favorable_result.weekly.loc[favorable_result.weekly.player_id.eq(3)]
    second_q = weaker_result.weekly.loc[weaker_result.weekly.player_id.eq(3)]
    assert first_q.appearance_probability.iloc[0] == second_q.appearance_probability.iloc[0]
    assert first_q.expected_points.iloc[0] > second_q.expected_points.iloc[0]
    for decision in (first, second):
        action = decision.search.best
        expected = independent_lineup_oracle(
            decision.squad,
            action.starting_xi,
            action.ordered_bench,
            action.captain_id,
            action.vice_captain_id,
        )
        assert action.expected_net_points == pytest.approx(expected, abs=1e-10)


def test_learned_concentration_cannot_credit_one_player_both_sides_of_physical_goal(model):
    case = native_case()
    selected = case.components.club.eq(3)
    for index, row in case.components.loc[selected].iterrows():
        share = 0.6 if row.player_code == 3 else 0.04
        case.components.loc[index, ["goals_share", "assists_share"]] = share
        case.components.loc[index, ["goals", "assists"]] = [1.2 * share, 0.9 * share]
    case = recompute_native_scores(case)
    labels = dict.fromkeys(case.roster.loc[case.roster.club_code.eq(3), "player_id"], 0)
    labels[3] = 100
    case = with_labels(case, labels)
    assert (case.components.goals + case.components.assists <= case.components.team_goal_rate).all()
    with pytest.raises(ValueError, match="physical"):
        compose(case, model)


@pytest.mark.parametrize("chip", [None, "3xc", "bboost"])
def test_selected_action_matches_independent_appearance_world_autosub_oracle(model, chip):
    result = compose(native_case(), model)
    decision = plan(result, chip=chip, hit_points=4)
    action = decision.search.best
    expected = independent_lineup_oracle(
        decision.squad,
        action.starting_xi,
        action.ordered_bench,
        action.captain_id,
        action.vice_captain_id,
        chip=chip,
        hits=4,
    )
    assert action.expected_net_points == pytest.approx(expected, rel=1e-11, abs=1e-10)


def test_locked_action_and_role_exclusions_are_preserved(model):
    result = compose(native_case(), model)
    decision = plan(result, locked_first=True)
    assert decision.search.best.starting_xi == XI
    assert decision.search.best.ordered_bench == BENCH
    assert (decision.search.best.captain_id, decision.search.best.vice_captain_id) == (13, 8)
    assert decision.search.evaluations == 1
    restricted = plan(result, not_starting=(6,), not_captain=(3,))
    assert 6 not in restricted.search.best.starting_xi
    assert 3 not in (restricted.search.best.captain_id, restricted.search.best.vice_captain_id)


@pytest.mark.parametrize("frame_name", ["components", "weekly", "roster"])
@pytest.mark.parametrize("kind", ["values", "attrs"])
def test_composed_frame_values_and_private_metadata_tampering_are_refused(model, frame_name, kind):
    result = compose(native_case(), model)
    frame = getattr(result, frame_name)
    if kind == "attrs":
        frame.attrs["private_tamper"] = "changed"
    else:
        column = "buy_price_tenths" if frame_name == "roster" else "expected_points"
        frame.loc[frame.index[0], column] += 1
    with pytest.raises(ValueError, match="changed"):
        plan(result)


@pytest.mark.parametrize("field", ["receipt_json", "resource_bundle_json"])
def test_receipt_or_resource_replacement_is_refused(model, field):
    result = compose(native_case(), model)
    payload = json.loads(getattr(result, field))
    payload["changed"] = True
    damaged = replace(result, **{field: json.dumps(payload, sort_keys=True, separators=(",", ":"))})
    with pytest.raises(ValueError):
        plan(damaged)


@pytest.mark.parametrize(
    "damage", ["source_hash", "future", "identity", "permission", "calendar", "native_basis"]
)
def test_raw_source_refusals_precede_composition(model, damage):
    case = native_case()
    document, fixtures = case_week_documents(case)[2]
    document = deepcopy(document)
    if damage == "future":
        document["captures"][-1]["published_at"] = DEADLINE_AT
    elif damage == "identity":
        document["captures"][-1]["element_id"] += 1
    elif damage == "permission":
        document["model_use_approved"] = False
    elif damage == "calendar":
        document["fixture_ids"] = []
    elif damage == "native_basis":
        document["native_basis_sha256"] = "a" * 64
    raw, digest = encoded(document)
    with pytest.raises(DataError):
        read_flag_week_source(
            raw + b" " if damage == "source_hash" else raw,
            sha256=digest,
            season=SEASON,
            gameweek=6,
            player_code=3,
            decision_at=DECISION_AT,
            deadline_at=DEADLINE_AT,
            native_fixtures=fixtures,
            native_basis_sha256=native_basis_digest(case.components),
        )


def test_original_legacy_rule_is_bound_to_captured_next_label_not_target_label(model):
    case = with_labels(native_case(), {3: 25})
    weeks = []
    for document, fixtures in case_week_documents(case):
        if document["player_code"] == 3:
            for capture in document["captures"]:
                capture["chance_of_playing_this_round"] = 75
                capture["chance_of_playing_next_round"] = 25
        weeks.append(parse_week_document(document, fixtures))
    focal = next(week for week in weeks if week.player_code == 3)
    assert focal.label == 75
    assert focal.legacy_next_round_label == 25
    result = compose(case, model, weeks=tuple(weeks))
    row = result.weekly.loc[result.weekly.player_id.eq(3)].iloc[0]
    assert row.appearance_probability == pytest.approx(model.predict(focal).weekly_appearance)
    assert json.loads(result.receipt_json)["captured_availability"]["3"] == 0.25


def test_source_facts_and_supplied_legacy_multiplier_must_agree(model):
    case = native_case()
    with pytest.raises(ValueError, match="legacy"):
        compose(case, model, labels={3: 25})


@pytest.mark.parametrize(
    "damage",
    ["missing_fixture", "duplicate_calendar", "decision", "native_mass", "old_weekly", "coverage"],
)
def test_native_calendar_and_control_bindings_are_refused(model, damage):
    case = native_case(double=True)
    if damage == "missing_fixture":
        case = replace(case, components=case.components.iloc[1:].copy())
    elif damage == "duplicate_calendar":
        case = replace(
            case, calendar=pd.concat([case.calendar, case.calendar.iloc[:1]], ignore_index=True)
        )
    elif damage == "decision":
        case.calendar.loc[0, "decision_at"] = DEADLINE_AT
    elif damage == "native_mass":
        case.components.loc[0, "minute_probability_0"] += 0.1
    elif damage == "old_weekly":
        case.weekly.loc[0, "expected_points"] += 0.5
    else:
        case.components.attrs["covered_gameweeks"] = []
    with pytest.raises(ValueError):
        compose(case, model)


@pytest.mark.parametrize(
    "component", ["clean_sheet_probability", "defcon_probability", "goals", "raw_expected_points"]
)
def test_internally_rebound_native_numerical_corruption_is_refused(component):
    case = native_case()
    case.components.loc[0, component] += 0.1
    if component == "raw_expected_points":
        case.components.loc[0, "expected_points"] += 0.1
    case = with_labels(case, {})
    with pytest.raises(ValueError):
        compose(case, enabled=False)


@pytest.mark.parametrize("damage", ["missing_gk", "four_from_club", "uncaptured", "duplicate"])
def test_fixed_fifteen_invalid_inventory_is_refused(model, damage):
    result = compose(native_case(), model)
    ids = list(range(1, 16))
    if damage == "missing_gk":
        ids[1] = 16
    elif damage == "four_from_club":
        ids[9] = 19
    elif damage == "uncaptured":
        ids[-1] = 9999
    else:
        ids[-1] = 14
    xi = tuple(19 if player == 10 and damage == "four_from_club" else player for player in XI)
    with pytest.raises((ValueError, EvaluationValidationError)):
        plan_flag_fixed_fifteen(result, ids, xi, BENCH, 13, 8, gameweek=6)


@pytest.mark.parametrize("damage", ["club_has_two_aliases", "alias_has_two_clubs"])
def test_roster_team_and_persistent_club_mapping_must_be_bidirectional(damage):
    case = native_case()
    if damage == "club_has_two_aliases":
        case.roster.loc[case.roster.player_id.eq(7), "team_id"] = 99
        assert case.roster.groupby("team_id").club_code.nunique().max() == 1
        assert case.roster.groupby("club_code").team_id.nunique().max() == 2
    else:
        case.roster.loc[case.roster.club_code.eq(2), "team_id"] = 1
        assert case.roster.groupby("club_code").team_id.nunique().max() == 1
        assert case.roster.groupby("team_id").club_code.nunique().max() == 2
    with pytest.raises(ValueError):
        compose(case, enabled=False)


@pytest.mark.parametrize("damage", ["row_clock", "row_season", "availability_attrs", "index"])
def test_disabled_native_guard_is_not_masked_by_rebound_learned_input(damage):
    case = native_case()
    if damage == "row_clock":
        case.components.loc[0, "decision_at"] = DEADLINE_AT
    elif damage == "row_season":
        case.components.loc[0, "season"] = "2024-25"
    elif damage == "availability_attrs":
        case.components.attrs["availability_application"] = "already_applied"
    else:
        case.components.index = [0] * len(case.components)
    with pytest.raises(ValueError):
        compose(case, enabled=False)


@pytest.mark.parametrize("mode", ["learned", "control", "disabled"])
def test_native_requires_explicit_unapplied_availability_marker(model, mode):
    case = native_case()
    del case.components.attrs["availability_application"]
    with pytest.raises(ValueError, match="precede the captured eligibility"):
        compose(case, model, enabled=mode != "disabled", control=mode == "control")


@pytest.mark.parametrize("max_evaluations", [0, 129, True])
def test_evaluation_budget_is_bounded_before_search(model, max_evaluations):
    result = compose(native_case(), model)
    with pytest.raises(ValueError):
        plan(result, max_evaluations=max_evaluations)


@pytest.mark.parametrize(
    "field,retained,attempt",
    [("chip", None, "3xc"), ("hit_points", 0, 4), ("locked_first", True, False)],
)
def test_captured_resource_policy_cannot_be_changed_by_role_search(model, field, retained, attempt):
    case = native_case()
    case.resource_bundle[field] = retained
    result = compose(case, model)
    with pytest.raises(ValueError, match="retained"):
        plan(result, **{field: attempt})
