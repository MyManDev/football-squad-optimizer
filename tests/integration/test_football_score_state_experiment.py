"""Raw source to paired process, unchanged native law and legal-role checks."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.football_score_state_fixtures import (
    BENCH,
    DEADLINE,
    DECISION,
    FIT_CUTOFF,
    SEASON,
    XI,
    case_documents,
    case_inputs,
    independent_lineup_score,
    independent_process_moments,
    invented_case,
    invented_training,
    native_moments,
    parse_snapshot,
)

from squadopt.application.football_score_state_experiment import (
    EXPERIMENT_VERSION,
    RECEIPT_ATTR,
    compose_score_state_experiment,
    native_basis_digest,
    plan_score_state_fixed_fifteen,
)
from squadopt.evaluation.models import EvaluationValidationError
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.prediction.football_minutes_role import ROLE_COMPONENT_COLUMNS
from squadopt.prediction.football_score_state import ScoreStateModel


@pytest.fixture(scope="module")
def model():
    return ScoreStateModel().fit(
        invented_training(),
        cutoff=FIT_CUTOFF,
        target_season=SEASON,
        target_gameweeks=(6,),
        allowed_seasons=("2023-24", "2024-25"),
        l2=0.2,
    )


def compose(case, model=None, *, fixtures=None, enabled=True, **flags):
    return compose_score_state_experiment(
        case.native,
        case.weekly,
        case.roster,
        case.calendar,
        case.resources,
        case_inputs(case)
        if fixtures is None and enabled
        else (() if fixtures is None else fixtures),
        model,
        season=SEASON,
        gameweeks=case.gameweeks,
        decision_at=DECISION,
        deadline_at=DEADLINE,
        captured_availability=case.eligibility,
        enabled=enabled,
        **flags,
    )


def plan(candidate, *, ids=tuple(range(1, 16)), xi=XI, bench=BENCH, captain=8, vice=3, **options):
    return plan_score_state_fixed_fifteen(
        candidate, ids, xi, bench, captain, vice, gameweek=6, **options
    )


def unmarked_equal(actual, expected):
    frame = actual.copy(deep=True)
    frame.attrs = {k: v for k, v in frame.attrs.items() if k != RECEIPT_ATTR}
    assert_frame_equal(frame, expected, check_exact=True)


def rebuild_served(case):
    served = case.weekly.copy(deep=True)
    served.attrs = deepcopy(case.weekly.attrs)
    for index, row in served.iterrows():
        mu = math.fsum(
            case.native.loc[case.native.player_code.eq(row.player_id), "expected_points"]
        )
        served.at[index, "expected_points"] = case.eligibility[int(row.player_id)] * mu
    return replace(case, weekly=served)


def test_raw_source_fit_paired_process_native_scoring_and_legal_roles_have_independent_oracles(
    model,
):
    case = invented_case()
    inputs = case_inputs(case)
    seals = tuple(
        native_basis_digest(frame)
        for frame in (case.native, case.weekly, case.roster, case.calendar)
    )
    candidate = compose(case, model, fixtures=inputs)
    changed = {
        "goals",
        "assists",
        "clean_sheet_probability",
        "team_goal_rate",
        "opponent_goal_rate",
        "raw_expected_points",
        "expected_points",
        "model_version",
    }
    assert_frame_equal(
        candidate.components[[c for c in case.native if c not in changed]],
        case.native[[c for c in case.native if c not in changed]],
        check_exact=True,
    )
    assert_frame_equal(
        candidate.weekly[[c for c in case.weekly if c != "expected_points"]],
        case.weekly[[c for c in case.weekly if c != "expected_points"]],
        check_exact=True,
    )
    for fixture in inputs:
        home, away, survival = independent_process_moments(
            fixture, model.metadata.coefficients, maximum_goals=24
        )
        process = model.predict(fixture)
        assert process.home_physical_goals == pytest.approx(home, abs=3e-7)
        assert process.away_physical_goals == pytest.approx(away, abs=3e-7)
        old = case.native.loc[case.native.fixture.eq(fixture.fixture_id)]
        new = candidate.components.loc[
            candidate.components.fixture.eq(fixture.fixture_id)
        ].set_index("player_code")
        for club, physical in ((fixture.home_club_code, home), (fixture.away_club_code, away)):
            side = old.loc[old.club.eq(club)]
            native_total = float(side.team_goal_rate.iloc[0])
            fraction_g = math.fsum(side.goals) / native_total
            fraction_a = math.fsum(side.assists) / native_total
            assert math.fsum(new.loc[new.club.eq(club), "goals"]) == pytest.approx(
                physical * fraction_g, abs=3e-7
            )
            assert math.fsum(new.loc[new.club.eq(club), "assists"]) == pytest.approx(
                physical * fraction_a, abs=3e-7
            )
            for native in side.to_dict("records"):
                pid = int(native["player_code"])
                source = next(p for p in fixture.players if p.player_code == pid)
                cs = math.fsum(
                    p * s
                    for p, m, s in zip(
                        source.probabilities, source.credited_minutes, survival[pid], strict=True
                    )
                    if m >= 60
                )
                goals = physical * fraction_g * native["goals_share"]
                assists = physical * fraction_a * native["assists_share"]
                direct = math.fsum(
                    (
                        native["appearance_probability"],
                        native["p60"],
                        {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}[native["position"]] * goals,
                        3 * assists,
                        {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}[native["position"]] * cs,
                        2 * native["defcon_probability"],
                        native["appearance_probability"] * native["residual_if_appearance"],
                    )
                )
                assert new.loc[pid, "clean_sheet_probability"] == pytest.approx(cs, abs=3e-7)
                assert new.loc[pid, "raw_expected_points"] == pytest.approx(direct, abs=3e-7)
                assert new.loc[pid, "expected_points"] == pytest.approx(max(0, direct), abs=3e-7)
    for row in candidate.weekly.itertuples():
        assert row.expected_points == pytest.approx(
            case.eligibility[int(row.player_id)]
            * math.fsum(
                candidate.components.loc[
                    candidate.components.player_code.eq(row.player_id), "expected_points"
                ]
            ),
            abs=2e-12,
        )
    decision = plan(candidate)
    chosen = decision.search.best
    assert chosen.expected_net_points == pytest.approx(
        independent_lineup_score(
            decision.squad,
            chosen.starting_xi,
            chosen.ordered_bench,
            chosen.captain_id,
            chosen.vice_captain_id,
        ),
        abs=2e-10,
    )
    assert decision.search.proof_scope == "bounded_fixed_squad_neighborhood_only"
    assert decision.resource_bundle_json == candidate.resource_bundle_json
    assert seals == tuple(
        native_basis_digest(frame)
        for frame in (case.native, case.weekly, case.roster, case.calendar)
    )


@pytest.mark.parametrize("control", (False, True))
def test_disabled_and_control_do_not_open_inputs_or_model_and_keep_dependent_dgw(control):
    case = invented_case(double=True)
    case.weekly.loc[case.weekly.player_id.eq(3), "appearance_probability"] = 0.75 * 0.88
    candidate = compose(case, object(), fixtures=object(), enabled=control, control=control)
    unmarked_equal(candidate.components, case.native)
    unmarked_equal(candidate.weekly, case.weekly)
    unmarked_equal(candidate.roster, case.roster)
    assert json.loads(candidate.resource_bundle_json) == case.resources


@pytest.mark.parametrize("fault", ("blank_nonzero", "single_below", "single_above"))
def test_served_appearance_must_be_coherent_without_inventing_a_dgw_union(fault):
    case = invented_case(blank=fault == "blank_nonzero")
    case.weekly.loc[0, "appearance_probability"] = {
        "blank_nonzero": 0.1,
        "single_below": 0.7,
        "single_above": 0.9,
    }[fault]
    with pytest.raises(ValueError, match="original served reference"):
        compose(case, object(), fixtures=object(), enabled=False)


def test_coherent_dgw_interior_appearance_is_retained_without_product_assumption(model):
    case = invented_case(double=True)
    # Both fixture marginals are .88. The supplied joint union .94 is coherent.
    # It is neither the perfectly dependent .88 nor the independent .9856.
    case.weekly.loc[case.weekly.player_id.eq(3), "appearance_probability"] = 0.75 * 0.94
    native = compose(case, object(), fixtures=object(), enabled=False)
    learned = compose(case, model)
    assert np.array_equal(native.weekly.appearance_probability, case.weekly.appearance_probability)
    assert np.array_equal(learned.weekly.appearance_probability, case.weekly.appearance_probability)


def test_zero_effect_ablation_checks_native_moments_and_dgw_points_once(model):
    case = invented_case(double=True)
    case.weekly.loc[case.weekly.player_id.eq(3), "appearance_probability"] = 0.75 * 0.88
    candidate = compose(case, model, zero_coefficients=True)
    assert np.allclose(
        candidate.weekly.expected_points, case.weekly.expected_points, rtol=0, atol=1e-9
    )
    assert np.array_equal(
        candidate.weekly.appearance_probability, case.weekly.appearance_probability
    )
    assert np.allclose(
        candidate.components.clean_sheet_probability,
        case.native.clean_sheet_probability,
        rtol=0,
        atol=1e-9,
    )
    assert candidate.components.model_version.eq(EXPERIMENT_VERSION).all()


def test_learned_physical_intervals_use_fpl_60_gate_without_mean_poisson_replacement(model):
    case = invented_case()
    candidate = compose(case, model)
    source = case_inputs(case)[1]
    process = model.predict(source)
    pid = 3
    person = next(p for p in source.players if p.player_code == pid)
    survival = next(p.survival for p in process.player_survival if p.player_code == pid)
    actual = candidate.components.loc[candidate.components.player_code.eq(pid)].iloc[0]
    independent = math.fsum(
        p * s
        for p, m, s in zip(person.probabilities, person.credited_minutes, survival, strict=True)
        if m >= 60
    )
    assert actual.clean_sheet_probability == pytest.approx(independent, abs=2e-12)
    naive = math.fsum(
        p * math.exp(-actual.opponent_goal_rate * m / 90)
        for p, m in zip(person.probabilities, person.credited_minutes, strict=True)
        if m >= 60
    )
    assert abs(independent - naive) > 1e-5
    assert independent < math.fsum(
        p * s for p, s in zip(person.probabilities, survival, strict=True)
    )


def test_same_credited_minutes_different_captured_physical_interval_changes_only_cs(model):
    case = invented_case()
    documents = list(case_documents(case))
    before = compose(case, model, fixtures=tuple(parse_snapshot(d) for d in documents))
    person = next(p for p in documents[1]["projection"]["players"] if p["player_code"] == 3)
    width = person["physical_off"][5] - person["physical_on"][5]
    person["physical_on"][5], person["physical_off"][5], person["exit_policies"][5] = (
        10.0,
        10.0 + width,
        "normal_substitution",
    )
    after = compose(case, model, fixtures=tuple(parse_snapshot(d) for d in documents))
    first, second = (
        before.components.set_index("player_code").loc[3],
        after.components.set_index("player_code").loc[3],
    )
    assert abs(first.clean_sheet_probability - second.clean_sheet_probability) > 1e-6
    assert first.goals == second.goals
    assert first.assists == second.assists
    assert first.expected_minutes == second.expected_minutes
    assert_frame_equal(
        before.weekly[["player_id", "appearance_probability"]],
        after.weekly[["player_id", "appearance_probability"]],
        check_exact=True,
    )


@pytest.mark.parametrize("chip", (None, "bboost", "3xc"))
def test_fixed_inventory_official_autosubs_captain_fallback_and_chips(model, chip):
    candidate = compose(invented_case(), model)
    decision = plan(candidate, chip=chip, hit_points=4, locked_first=True)
    best = decision.search.best
    assert best.starting_xi == XI and best.ordered_bench == BENCH
    assert best.expected_net_points == pytest.approx(
        independent_lineup_score(
            decision.squad,
            best.starting_xi,
            best.ordered_bench,
            best.captain_id,
            best.vice_captain_id,
            chip=chip,
            hits=4,
        ),
        abs=2e-10,
    )


def test_blank_week_requires_verified_calendar_and_keeps_zero_without_process(model):
    candidate = compose(invented_case(blank=True), model)
    assert candidate.components.empty
    assert candidate.weekly.expected_points.eq(0).all()
    assert candidate.weekly.appearance_probability.eq(0).all()


@pytest.mark.parametrize(
    "fault",
    (
        "native_clock",
        "native_eligibility",
        "native_numeric",
        "original_mu",
        "original_q",
        "unsupported_version",
        "native_row_missing",
        "calendar_duplicate",
        "calendar_side_missing",
        "calendar_future_season",
        "calendar_incomplete",
        "calendar_uncaptured_clubs",
        "one_club_two_aliases",
        "one_alias_two_clubs",
        "factor_source_missing",
    ),
)
def test_original_native_capture_refusals(fault):
    case = invented_case()
    if fault == "native_clock":
        case.native.loc[0, "decision_at"] = "2026-09-22T11:00:00Z"
    elif fault == "native_eligibility":
        case.native.loc[0, "availability_multiplier"] = 0.75
    elif fault == "native_numeric":
        case.native.loc[0, "goals"] = math.nan
    elif fault == "original_mu":
        case.weekly.loc[0, "expected_points"] += 1
    elif fault == "original_q":
        case.weekly.loc[0, "appearance_probability"] = math.inf
    elif fault == "unsupported_version":
        case.native["model_version"] = "not_a_native_version"
    elif fault == "native_row_missing":
        case = replace(case, native=case.native.iloc[1:].copy())
    elif fault == "calendar_duplicate":
        case = replace(
            case, calendar=pd.concat((case.calendar, case.calendar.iloc[[0]]), ignore_index=True)
        )
    elif fault == "calendar_side_missing":
        case = replace(case, calendar=case.calendar.iloc[1:].copy())
    elif fault == "calendar_future_season":
        case.calendar["kickoff"] = "2028-09-23T15:00:00Z"
        case.native["kickoff"] = "2028-09-23T15:00:00Z"
    elif fault == "calendar_incomplete":
        case.calendar.attrs["calendar_complete"] = False
    elif fault == "calendar_uncaptured_clubs":
        added = case.calendar.iloc[:2].copy()
        added["fixture"] = 99
        added["club"] = [70, 80]
        added["opponent"] = [80, 70]
        schedule = pd.concat((case.calendar, added), ignore_index=True)
        schedule.attrs = deepcopy(case.calendar.attrs)
        case = replace(case, calendar=schedule)
    elif fault == "one_club_two_aliases":
        case.roster.loc[6, "team_id"] = 70
    elif fault == "one_alias_two_clubs":
        case.roster.loc[case.roster.club_code.eq(2), "team_id"] = 1
    elif fault == "factor_source_missing":
        case.native.attrs.pop("captured_availability_sha256")
    with pytest.raises(ValueError):
        compose(case, enabled=False)


@pytest.mark.parametrize(
    "fault",
    (
        "physical_clock_moment",
        "minute_law",
        "late_capture",
        "own_opponent",
        "person_ambiguous",
        "missing_player",
        "policy_unknown",
        "basis_digest",
        "original_model",
    ),
)
def test_enabled_raw_source_identity_clock_and_moment_refusals(model, fault):
    case = invented_case()
    docs = list(case_documents(case))
    target = docs[0]
    if fault == "physical_clock_moment":
        person = target["projection"]["players"][0]
        person["physical_off"][2] -= 1
    elif fault == "minute_law":
        target["projection"]["players"][0]["credited_minutes"][2] -= 1
    elif fault == "late_capture":
        target["published_at"] = "2026-09-22T12:00:01Z"
    elif fault == "own_opponent":
        target["projection"]["away_club_code"] = target["projection"]["home_club_code"]
    elif fault == "person_ambiguous":
        target["person_mapping"][1]["provider_id"] = target["person_mapping"][0]["provider_id"]
    elif fault == "missing_player":
        target["projection"]["players"].pop()
    elif fault == "policy_unknown":
        target["projection"]["players"][0]["exit_policies"][2] = "dismissed"
    elif fault == "basis_digest":
        target["projection"]["native_basis_sha256"] = "b" * 64
    elif fault == "original_model":
        target["projection"]["native_model_version"] = "football_team_share_v1"
    with pytest.raises(ValueError):
        compose(case, model, fixtures=tuple(parse_snapshot(d) for d in docs))


@pytest.mark.parametrize(
    "fault", ("component", "weekly_q", "inventory_extra", "attrs", "index", "resources", "receipt")
)
def test_private_receipt_and_captured_resource_tamper_refusals(fault):
    candidate = compose(invented_case(), enabled=False)
    if fault == "component":
        candidate.components.loc[0, "goals"] += 0.01
    elif fault == "weekly_q":
        candidate.weekly.loc[0, "appearance_probability"] *= 0.75
    elif fault == "inventory_extra":
        candidate.roster.loc[0, "ownership_receipt"] = "another-original-capture"
    elif fault == "attrs":
        candidate.roster.attrs["native_private_inventory"]["bank"] = 18
    elif fault == "index":
        candidate.weekly.index = candidate.weekly.index + 1
    elif fault == "resources":
        candidate = replace(
            candidate,
            resource_bundle_json=candidate.resource_bundle_json.replace(
                '"bank_tenths":17', '"bank_tenths":18'
            ),
        )
    elif fault == "receipt":
        candidate = replace(
            candidate,
            receipt_json=candidate.receipt_json.replace('"enabled":false', '"enabled":true'),
        )
    with pytest.raises(ValueError):
        plan(candidate)


@pytest.mark.parametrize(
    "fault",
    (
        "other_owned",
        "unavailable_chip",
        "over_budget",
        "four_from_club",
        "missing_gk",
        "retained_hits",
    ),
)
def test_fixed_fifteen_inventory_constraints_are_independently_preserved(fault):
    case = invented_case()
    ids, xi, bench, options = tuple(range(1, 16)), XI, BENCH, {}
    if fault == "other_owned":
        ids = tuple(22 if p == 10 else p for p in ids)
        xi = tuple(22 if p == 10 else p for p in xi)
    elif fault == "unavailable_chip":
        case.resources["chips"]["bboost"] = False
        options["chip"] = "bboost"
    elif fault == "over_budget":
        options["max_evaluations"] = 129
    elif fault == "four_from_club":
        ids = tuple(19 if p == 10 else p for p in ids)
        xi = tuple(19 if p == 10 else p for p in xi)
        case.resources["owned"] = list(ids)
    elif fault == "missing_gk":
        ids = tuple(20 if p == 2 else p for p in ids)
        bench = tuple(20 if p == 2 else p for p in bench)
        case.resources["owned"] = list(ids)
    elif fault == "retained_hits":
        case.resources["hit_points"] = 0
        options["hit_points"] = 4
    match = r"permits at most 128 evaluations\.$" if fault == "over_budget" else None
    with pytest.raises((ValueError, EvaluationValidationError), match=match):
        plan(compose(case, enabled=False), ids=ids, xi=xi, bench=bench, **options)


@pytest.mark.parametrize(
    "fault", ("numeric_budget", "wrong_receipt", "missing_survival", "wrong_fixture")
)
def test_prediction_numerical_and_identity_receipts_are_checked(model, monkeypatch, fault):
    case = invented_case()
    inputs = case_inputs(case)
    original = model.predict

    def corrupt(fixture, **flags):
        result = original(fixture, **flags)
        if fault == "numeric_budget":
            return replace(result, goal_moment_error_bound=1e-4)
        if fault == "wrong_receipt":
            return replace(result, input_sha256="c" * 64)
        if fault == "missing_survival":
            return replace(result, player_survival=result.player_survival[:-1])
        return replace(
            result, fixture=inputs[1] if fixture.fixture_id == inputs[0].fixture_id else fixture
        )

    monkeypatch.setattr(model, "predict", corrupt)
    with pytest.raises(ValueError):
        compose(case, model, fixtures=inputs)


@pytest.mark.parametrize("missing", (None, pd.NA, math.nan), ids=("null", "pandas_na", "nan"))
def test_unknown_native_roles_are_exact_disabled_control_and_missing_types_are_sealed(missing):
    case = invented_case()
    for index, row in case.native.iterrows():
        probabilities = (*(row[f"minute_probability_{b}"] for b in range(4)), 0.0, 0.0, 0.0)
        minutes = (*(row[f"minute_value_{b}"] for b in range(4)), 10.0, 65.0, 90.0)
        values = native_moments(row, probabilities, minutes)
        case.native.loc[index, list(values)] = list(values.values())
    for column in ROLE_COMPONENT_COLUMNS:
        if column.startswith(("start_", "cameo_")):
            case.native[column] = pd.Series([missing] * len(case.native), dtype="object")
    case.native["minute_role_status"] = "unavailable_no_known_start_labels"
    case.native["known_start_label_rows"] = 0
    case.native["unknown_start_label_rows"] = 80
    case.native["unknown_role_probability"] = case.native.appearance_probability
    case = rebuild_served(case)
    candidate = compose(case, object(), fixtures=object(), enabled=False)
    unmarked_equal(candidate.components, case.native)
    plan(candidate, max_evaluations=1, locked_first=True)
    candidate.components.loc[0, "start_probability"] = math.nan if missing is None else None
    with pytest.raises(ValueError, match="changed"):
        plan(candidate, max_evaluations=1, locked_first=True)


def test_explicit_four_bin_native_clock_is_supported_without_invented_start_roles(model):
    case = invented_case()
    for index, row in case.native.iterrows():
        probabilities = (*(row[f"minute_probability_{b}"] for b in range(4)), 0.0, 0.0, 0.0)
        minutes = (*(row[f"minute_value_{b}"] for b in range(4)), 10.0, 65.0, 90.0)
        values = native_moments(row, probabilities, minutes)
        case.native.loc[index, list(values)] = list(values.values())
    case.native["model_version"] = FOOTBALL_MODEL_VERSION
    case.native.attrs["joint_role"] = False
    case = rebuild_served(case)
    source = case_inputs(case)
    assert all(p.minute_representation == "four_bins" for f in source for p in f.players)
    candidate = compose(case, model, fixtures=source, zero_coefficients=True)
    assert np.allclose(
        candidate.weekly.expected_points, case.weekly.expected_points, rtol=0, atol=1e-9
    )
    assert np.array_equal(
        candidate.weekly.appearance_probability, case.weekly.appearance_probability
    )


def test_zero_native_physical_goal_channel_remains_zero_with_retained_recipients(model):
    case = invented_case()
    own = case.native.club.eq(1)
    opposing = case.native.opponent.eq(1)
    case.native.loc[own, ["team_goal_rate", "goals", "assists"]] = 0
    case.native.loc[opposing, "opponent_goal_rate"] = 0
    for index, row in case.native.iterrows():
        values = native_moments(row)
        case.native.loc[index, list(values)] = list(values.values())
    case = rebuild_served(case)
    candidate = compose(case, model)
    assert candidate.components.loc[own, "team_goal_rate"].eq(0).all()
    assert candidate.components.loc[own, "goals"].eq(0).all()
    assert candidate.components.loc[own, "assists"].eq(0).all()
    assert np.array_equal(candidate.components.goals_share, case.native.goals_share)


def test_learned_score_flow_changes_legal_xi_reserve_order_and_fallback_with_same_inventory(model):
    case = invented_case()
    index = case.native.index[case.native.player_code.eq(6)][0]
    # The original synthetic empirical residual is a fixed input in both arms.
    case.native.at[index, "residual_if_appearance"] = -1.0
    for key, value in native_moments(case.native.loc[index].to_dict()).items():
        case.native.at[index, key] = value
    case = rebuild_served(case)
    control = plan(compose(case, model, control=True))
    learned = plan(compose(case, model))
    old, new = control.search.best, learned.search.best
    assert set(old.starting_xi) != set(new.starting_xi)
    assert old.ordered_bench != new.ordered_bench
    assert old.vice_captain_id != new.vice_captain_id
    assert old.captain_id == new.captain_id == 8
    assert_frame_equal(
        control.squad.drop(columns="expected_points"),
        learned.squad.drop(columns="expected_points"),
        check_exact=True,
        check_flags=True,
    )
    assert control.resource_bundle_json == learned.resource_bundle_json

    def value(squad, action):
        return independent_lineup_score(
            squad,
            action.starting_xi,
            action.ordered_bench,
            action.captain_id,
            action.vice_captain_id,
        )

    # Independent appearance worlds prove the ordering flips for these two legal actions.
    old_on_old, new_on_old = value(control.squad, old), value(control.squad, new)
    old_on_new, new_on_new = value(learned.squad, old), value(learned.squad, new)
    assert old_on_old > new_on_old
    assert new_on_new > old_on_new
    assert old.expected_net_points == pytest.approx(old_on_old, abs=2e-10)
    assert new.expected_net_points == pytest.approx(new_on_new, abs=2e-10)
