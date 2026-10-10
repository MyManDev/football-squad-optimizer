"""Independent raw-source, component and legal-role checks for private workload use."""

from __future__ import annotations

import json
import math
from copy import deepcopy
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.football_load_fixtures import (
    BENCH,
    DEADLINE,
    DECISION,
    FIT_CUTOFF,
    LAW,
    SEASON,
    XI,
    appearance_world_score,
    case_documents,
    case_inputs,
    document_bytes,
    native_case,
    parse_workload,
    score_row,
    training_inputs,
)

from squadopt.application.football_load_experiment import (
    RECEIPT_ATTR,
    compose_load_experiment,
    native_basis_digest,
    plan_load_fixed_fifteen,
)
from squadopt.data.errors import DataError
from squadopt.evaluation.models import EvaluationValidationError
from squadopt.features.football_load_inputs import (
    native_joint_law_digest,
    read_load_snapshot,
)
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.prediction.football_load_minutes import LoadMinutesModel
from squadopt.prediction.football_minutes_role import ROLE_COMPONENT_COLUMNS


@pytest.fixture(scope="module")
def model():
    return LoadMinutesModel().fit(
        training_inputs(),
        cutoff=FIT_CUTOFF,
        target_season=SEASON,
        target_gameweeks=(6, 7),
        l2=0.05,
    )


def compose(case, model=None, *, weeks=None, enabled=True, **options):
    return compose_load_experiment(
        case.components,
        case.weekly,
        case.roster,
        case.calendar,
        case.resources,
        case_inputs(case) if weeks is None and enabled else (() if weeks is None else weeks),
        model,
        season=SEASON,
        gameweeks=case.gameweeks,
        decision_at=DECISION,
        deadline_at=DEADLINE,
        captured_availability=case.eligibility,
        enabled=enabled,
        **options,
    )


def served_again(case):
    weekly = case.weekly.copy(deep=True)
    weekly.attrs = deepcopy(case.weekly.attrs)
    for index, row in weekly.iterrows():
        rows = case.components.loc[
            case.components.player_code.eq(row.player_id) & case.components.GW.eq(row.gameweek)
        ]
        weekly.at[index, "expected_points"] = case.eligibility[int(row.player_id)] * math.fsum(
            rows.expected_points
        )
        weekly.at[index, "appearance_probability"] = case.eligibility[int(row.player_id)] * (
            1 - math.prod(1 - q for q in rows.appearance_probability)
        )
    return replace(case, weekly=weekly)


def unknown_role_case(missing=None):
    """The native four-bin control whose starting roles remain unknown."""
    case = native_case()
    frame = case.components.copy(deep=True)
    for index, row in frame.iterrows():
        probabilities = (*(float(row[f"minute_probability_{i}"]) for i in range(4)), 0.0, 0.0, 0.0)
        minutes = (*(float(row[f"minute_value_{i}"]) for i in range(4)), 10.0, 65.0, 90.0)
        values = score_row(row, probabilities, minutes)
        frame.loc[index, list(values)] = list(values.values())
    for column in ROLE_COMPONENT_COLUMNS:
        if column.startswith(("start_", "cameo_")):
            frame[column] = pd.Series([missing] * len(frame), dtype="object")
    frame["minute_role_status"] = "unavailable_no_known_start_labels"
    frame["known_start_label_rows"] = 0
    frame["unknown_start_label_rows"] = 80
    frame["unknown_role_probability"] = frame.appearance_probability
    return served_again(replace(case, components=frame))


def assert_unmarked_equal(actual, expected):
    actual = actual.copy(deep=True)
    actual.attrs = {k: v for k, v in actual.attrs.items() if k != RECEIPT_ATTR}
    assert_frame_equal(actual, expected, check_exact=True)


def plan(candidate, *, ids=tuple(range(1, 16)), xi=XI, bench=BENCH, **options):
    return plan_load_fixed_fifteen(candidate, ids, xi, bench, 8, 3, gameweek=6, **options)


def test_raw_sources_fit_fixture_week_and_roles_match_independent_oracles(model):
    case = native_case(double=True)
    weeks = case_inputs(case, heavy_players=(3, 8, 13))
    original_hashes = tuple(
        native_basis_digest(f)
        for f in (
            case.components,
            case.weekly,
            case.roster,
            case.calendar,
        )
    )
    candidate = compose(case, model, weeks=weeks)
    predictions = {(w.player_code, w.gameweek): model.predict(w) for w in weeks}
    learned = candidate.components.set_index(["player_code", "fixture"])
    expected_minutes = {}
    for key, prediction in predictions.items():
        for fixture, marginal in zip(
            prediction.week.fixtures, prediction.fixture_probabilities, strict=True
        ):
            expected_minutes[key[0], fixture.fixture_id] = math.fsum(
                p * m for p, m in zip(marginal, fixture.minutes, strict=True)
            )
    for _, group in case.components.groupby(["GW", "fixture", "club"]):
        weights = {
            int(row.player_code): expected_minutes[int(row.player_code), int(row.fixture)]
            / float(row.expected_minutes)
            for row in group.itertuples()
        }
        for native in group.to_dict("records"):
            pid, fid = int(native["player_code"]), int(native["fixture"])
            row = learned.loc[pid, fid]
            independent = dict(native)
            for count in ("goals", "assists"):
                denominator = math.fsum(
                    r[count + "_share"] * weights[int(r["player_code"])]
                    for r in group.to_dict("records")
                )
                share = native[count + "_share"] * weights[pid] / denominator
                independent[count] = math.fsum(group[count]) * share
                assert row[count + "_share"] == pytest.approx(share, abs=2e-12)
                assert row[count] == pytest.approx(independent[count], abs=2e-12)
            prediction = predictions[pid, int(native["GW"])]
            f = next(
                i for i, fixture in enumerate(prediction.week.fixtures) if fixture.fixture_id == fid
            )
            oracle = score_row(
                independent,
                prediction.fixture_probabilities[f],
                prediction.week.fixtures[f].minutes,
            )
            for name in (
                "appearance_probability",
                "expected_minutes",
                "p60",
                "clean_sheet_probability",
                "defcon_probability",
                "raw_expected_points",
                "expected_points",
            ):
                assert row[name] == pytest.approx(oracle[name], abs=2e-10)
        for count in ("goals", "assists"):
            assert math.fsum(
                learned.loc[(group.player_code.tolist(), int(group.fixture.iloc[0])), count]
            ) == pytest.approx(math.fsum(group[count]), abs=2e-12)
    for row in candidate.weekly.itertuples():
        p = predictions[int(row.player_id), int(row.gameweek)]
        q = math.fsum(
            weight for state, weight in zip(p.states, p.probabilities, strict=True) if any(state)
        )
        fixture_points = candidate.components.loc[
            candidate.components.player_code.eq(row.player_id)
            & candidate.components.GW.eq(row.gameweek),
            "expected_points",
        ]
        e = case.eligibility[int(row.player_id)]
        assert row.appearance_probability == pytest.approx(e * q, abs=2e-12)
        assert row.expected_points == pytest.approx(e * math.fsum(fixture_points), abs=2e-12)
    choice = plan(candidate)
    best = choice.search.best
    assert best.expected_net_points == pytest.approx(
        appearance_world_score(
            choice.squad,
            best.starting_xi,
            best.ordered_bench,
            best.captain_id,
            best.vice_captain_id,
        ),
        abs=2e-10,
    )
    assert original_hashes == tuple(
        native_basis_digest(f)
        for f in (
            case.components,
            case.weekly,
            case.roster,
            case.calendar,
        )
    )
    assert choice.resource_bundle_json == candidate.resource_bundle_json
    assert choice.search.proof_scope == "bounded_fixed_squad_neighborhood_only"


def test_recorded_load_changes_legal_roles_without_changing_owned_resources(model):
    case = native_case()
    light = compose(case, model, weeks=case_inputs(case))
    loaded = compose(case, model, weeks=case_inputs(case, heavy_players=(3, 8, 13)))
    for pid in (3, 8, 13):
        a = light.weekly.set_index("player_id").loc[pid]
        b = loaded.weekly.set_index("player_id").loc[pid]
        assert b.appearance_probability < a.appearance_probability
        assert (
            loaded.components.loc[loaded.components.player_code.eq(pid), "expected_minutes"].iloc[0]
            < light.components.loc[light.components.player_code.eq(pid), "expected_minutes"].iloc[0]
        )
    one, two = plan(light), plan(loaded)
    assert one.search.best.fingerprint != two.search.best.fingerprint
    assert two.search.best.starting_xi != XI
    assert two.search.best.ordered_bench != BENCH
    assert two.search.best.captain_id != 8
    assert one.resource_bundle_json == two.resource_bundle_json
    assert set(two.squad.player_id) == set(range(1, 16))
    for field in case.roster.columns:
        assert_frame_equal(two.squad[[field]], case.roster.iloc[:15][[field]], check_exact=True)
    assert two.search.best.expected_net_points >= two.search.incumbent.expected_net_points


@pytest.mark.parametrize("control", (False, True))
def test_disabled_and_control_return_exact_original_frames_without_model(control):
    case = native_case(double=True)
    candidate = compose(case, enabled=control, control=control)
    for actual, original in (
        (candidate.components, case.components),
        (candidate.weekly, case.weekly),
        (candidate.roster, case.roster),
    ):
        assert_unmarked_equal(actual, original)
    assert json.loads(candidate.resource_bundle_json) == case.resources


@pytest.mark.parametrize(
    ("enabled", "control", "zero_coefficients"),
    ((False, True, False), (False, False, True), (True, True, True)),
)
def test_contradictory_switches_refuse_instead_of_mislabelling_the_receipt(
    model, enabled, control, zero_coefficients
):
    case = native_case()
    with pytest.raises(ValueError, match="separate enabled learned arm"):
        compose(
            case,
            model,
            enabled=enabled,
            control=control,
            zero_coefficients=zero_coefficients,
        )


def test_zero_coefficient_ablation_retains_arbitrary_correlated_native_week_law(model):
    case = native_case(double=True)
    values = []
    for document, fixtures, states, probabilities in case_documents(case):
        if document["player_code"] == 3:
            probabilities = tuple(
                LAW[state[0]] if state[0] == state[1] else 0.0 for state in states
            )
            document["native_joint_law_sha256"] = native_joint_law_digest(
                fixtures, states, probabilities
            )
            case.weekly.loc[case.weekly.player_id.eq(3), "appearance_probability"] = (
                case.eligibility[3] * (1 - LAW[0])
            )
        values.append(parse_workload(document, fixtures, states, probabilities))
    candidate = compose(case, model, weeks=tuple(values), zero_coefficients=True)
    assert np.allclose(
        candidate.weekly.expected_points, case.weekly.expected_points, atol=2e-10, rtol=0
    )
    assert np.allclose(
        candidate.weekly.appearance_probability,
        case.weekly.appearance_probability,
        atol=2e-12,
        rtol=0,
    )
    q = candidate.weekly.loc[candidate.weekly.player_id.eq(3), "appearance_probability"].iloc[0]
    assert q == pytest.approx(0.75 * 0.88)
    assert q != pytest.approx(0.75 * (1 - 0.12**2))
    control = compose(case, weeks=tuple(values), control=True)
    assert_unmarked_equal(control.weekly, case.weekly)


def test_incompatible_served_product_control_refuses_correlated_joint_source():
    case = native_case(double=True)
    values = []
    for document, fixtures, states, probabilities in case_documents(case):
        if document["player_code"] == 3:
            probabilities = tuple(
                LAW[state[0]] if state[0] == state[1] else 0.0 for state in states
            )
            document["native_joint_law_sha256"] = native_joint_law_digest(
                fixtures, states, probabilities
            )
        values.append(parse_workload(document, fixtures, states, probabilities))
    with pytest.raises(ValueError, match="served control"):
        compose(case, weeks=tuple(values), control=True)


def test_dgw_uses_learned_joint_appearance_then_external_factor_once(model):
    case = native_case(double=True)
    weeks = case_inputs(case, heavy_players=(3,))
    candidate = compose(case, model, weeks=weeks)
    prediction = model.predict(next(w for w in weeks if w.player_code == 3))
    joint_q = math.fsum(
        p for s, p in zip(prediction.states, prediction.probabilities, strict=True) if any(s)
    )
    union_q = 1 - math.prod(m[0] for m in prediction.fixture_probabilities)
    assert abs(joint_q - union_q) > 1e-4
    row = candidate.weekly.set_index("player_id").loc[3]
    assert row.appearance_probability == pytest.approx(0.75 * joint_q, abs=2e-12)
    assert row.appearance_probability != pytest.approx(0.75**2 * joint_q)
    assert row.expected_points == pytest.approx(
        0.75
        * math.fsum(
            candidate.components.loc[candidate.components.player_code.eq(3), "expected_points"]
        )
    )


def test_state_clean_sheet_and_defcon_expectation_differs_from_mean_minutes(model):
    case = native_case()
    weeks = case_inputs(case, heavy_players=(3,))
    candidate = compose(case, model, weeks=weeks)
    row = candidate.components.loc[candidate.components.player_code.eq(3)].iloc[0]
    p = model.predict(next(w for w in weeks if w.player_code == 3))
    oracle = score_row(row, p.fixture_probabilities[0], p.week.fixtures[0].minutes)
    assert row.clean_sheet_probability == pytest.approx(oracle["clean_sheet_probability"])
    assert row.defcon_probability == pytest.approx(oracle["defcon_probability"])
    approximate = row.p60 * math.exp(
        -row.opponent_goal_rate * row.expected_minutes_if_appearance / 90
    )
    assert abs(row.clean_sheet_probability - approximate) > 1e-4


def test_blank_week_is_verified_zero_without_source_or_model_guess(model):
    case = native_case(blank=True)
    candidate = compose(case, model)
    assert candidate.components.empty
    assert candidate.weekly.expected_points.eq(0).all()
    assert candidate.weekly.appearance_probability.eq(0).all()
    choice = plan(candidate)
    assert choice.search.best.expected_net_points == 0


@pytest.mark.parametrize("chip", (None, "bboost", "3xc"))
def test_official_autosubs_captain_fallback_chip_and_hit_oracle(model, chip):
    case = native_case()
    candidate = compose(case, model, weeks=case_inputs(case, heavy_players=(8,)))
    choice = plan(candidate, chip=chip, hit_points=4, locked_first=True)
    best = choice.search.best
    assert best.starting_xi == XI
    assert best.ordered_bench == BENCH
    assert best.expected_net_points == pytest.approx(
        appearance_world_score(
            choice.squad,
            best.starting_xi,
            best.ordered_bench,
            best.captain_id,
            best.vice_captain_id,
            chip=chip,
            hits=4,
        ),
        abs=2e-10,
    )


def test_gk_goal_value_and_negative_raw_clipping_remain_native_rules(model):
    case = native_case()
    candidate = compose(case, model)
    for pid in (1, 66):
        row = candidate.components.loc[candidate.components.player_code.eq(pid)].iloc[0]
        weeks = case_inputs(case)
        p = model.predict(next(w for w in weeks if w.player_code == pid))
        oracle = score_row(row, p.fixture_probabilities[0], p.week.fixtures[0].minutes)
        assert row.raw_expected_points == pytest.approx(oracle["raw_expected_points"])
        assert row.expected_points == max(0, row.raw_expected_points)
    assert (
        candidate.components.loc[
            candidate.components.player_code.eq(66), "raw_expected_points"
        ].iloc[0]
        < 0
    )


@pytest.mark.parametrize(
    "fault",
    (
        "native_clock",
        "native_season",
        "native_eligibility",
        "native_model",
        "native_nan",
        "legacy_mu",
        "legacy_q",
        "legacy_q_over_eligibility",
        "legacy_q_nonfinite",
        "missing_fixture_row",
        "duplicate_fixture_row",
        "calendar_duplicate",
        "calendar_missing_opponent",
        "calendar_clock",
        "calendar_before_deadline",
        "consistent_out_of_season",
        "coverage",
        "club_to_two_aliases",
        "alias_to_two_clubs",
        "source_receipt",
        "availability_receipt",
        "availability_already_applied",
        "availability_undeclared",
    ),
)
def test_original_basis_and_comparator_refusals(fault):
    case = native_case()
    if fault == "native_clock":
        case.components.loc[0, "decision_at"] = "2026-09-22T11:00:00Z"
    elif fault == "native_season":
        case.components.loc[0, "season"] = "2024-25"
    elif fault == "native_eligibility":
        case.components.loc[0, "availability_multiplier"] = 0.75
    elif fault == "native_model":
        case.components.loc[0, "model_version"] = "unknown_native_v1"
    elif fault == "native_nan":
        case.components.loc[0, "goals"] = math.nan
    elif fault == "legacy_mu":
        case.weekly.loc[0, "expected_points"] += 0.1
    elif fault == "legacy_q":
        case.weekly.loc[0, "appearance_probability"] = -0.1
    elif fault == "legacy_q_over_eligibility":
        case.weekly.loc[case.weekly.player_id.eq(3), "appearance_probability"] = 0.8
    elif fault == "legacy_q_nonfinite":
        case.weekly.loc[0, "appearance_probability"] = math.inf
    elif fault == "missing_fixture_row":
        case = replace(case, components=case.components.iloc[1:].copy())
    elif fault == "duplicate_fixture_row":
        case = replace(
            case,
            components=pd.concat((case.components, case.components.iloc[[0]]), ignore_index=True),
        )
    elif fault == "calendar_duplicate":
        case = replace(
            case, calendar=pd.concat((case.calendar, case.calendar.iloc[[0]]), ignore_index=True)
        )
    elif fault == "calendar_missing_opponent":
        case = replace(case, calendar=case.calendar.iloc[1:].copy())
    elif fault == "calendar_clock":
        case.calendar.loc[0, "decision_at"] = "2026-09-22T11:00:00Z"
    elif fault == "calendar_before_deadline":
        case.calendar.loc[0, "kickoff"] = DEADLINE
    elif fault == "consistent_out_of_season":
        case.calendar["kickoff"] = "2028-09-23T15:00:00Z"
        case.components["kickoff"] = "2028-09-23T15:00:00Z"
    elif fault == "coverage":
        case.calendar.attrs["calendar_complete"] = False
    elif fault == "club_to_two_aliases":
        case.roster.loc[6, "team_id"] = 80
    elif fault == "alias_to_two_clubs":
        case.roster.loc[case.roster.club_code.eq(2), "team_id"] = 1
    elif fault == "source_receipt":
        case.components.attrs.pop("captured_availability_sha256")
    elif fault == "availability_receipt":
        case.components.attrs.pop("captured_availability_evidence_ref")
    elif fault == "availability_already_applied":
        case.components.attrs["availability_application"] = "applied_once"
    elif fault == "availability_undeclared":
        case.components.attrs.pop("availability_application")
    with pytest.raises(ValueError):
        compose(case, enabled=False)


@pytest.mark.parametrize(
    "fault",
    (
        "late_publication",
        "unknown_permission",
        "incomplete_coverage",
        "ambiguous_uid",
        "unfinalized_club",
        "short_recorded_exposure",
        "missing_native_target",
        "changed_joint",
    ),
)
def test_raw_source_causal_and_identity_refusals(fault):
    case = native_case(double=True)
    document, fixtures, states, probabilities = next(iter(case_documents(case)))
    if fault == "late_publication":
        document["published_at"] = "2026-09-22T12:00:01Z"
    elif fault == "unknown_permission":
        document["model_use_approved"] = False
    elif fault == "incomplete_coverage":
        document["coverage"]["complete"] = False
    elif fault == "ambiguous_uid":
        document["mapping"]["player_aliases"].append(
            {**document["mapping"]["player_aliases"][0], "player_code": 777}
        )
    elif fault == "unfinalized_club":
        document["club_matches"][0]["settled_at"] = None
    elif fault == "short_recorded_exposure":
        document["matches"][0]["recorded_exit_at"] = document["matches"][0]["kickoff"]
    elif fault == "missing_native_target":
        document["upcoming_fixtures"].pop(0)
    elif fault == "changed_joint":
        probabilities = tuple(reversed(probabilities))
    with pytest.raises(DataError):
        parse_workload(document, fixtures, states, probabilities)


@pytest.mark.parametrize(
    "fault",
    (
        "component_value",
        "weekly_value",
        "roster_extra",
        "frame_attrs",
        "frame_index",
        "resource_value",
        "receipt_value",
    ),
)
def test_private_output_receipt_and_resource_tamper_refusals(fault):
    candidate = compose(native_case(), enabled=False)
    if fault == "component_value":
        candidate.components.loc[0, "goals"] += 0.1
    elif fault == "weekly_value":
        candidate.weekly.loc[0, "appearance_probability"] *= 0.5
    elif fault == "roster_extra":
        candidate.roster.loc[0, "purchase_snapshot"] = "different-original-owner"
    elif fault == "frame_attrs":
        candidate.roster.attrs["private_state"]["bank"] = 99
    elif fault == "frame_index":
        candidate.weekly.index = candidate.weekly.index + 1
    elif fault == "resource_value":
        candidate = replace(
            candidate,
            resource_bundle_json=candidate.resource_bundle_json.replace(
                '"bank_tenths":18', '"bank_tenths":19'
            ),
        )
    elif fault == "receipt_value":
        candidate = replace(
            candidate,
            receipt_json=candidate.receipt_json.replace('"enabled":false', '"enabled":true'),
        )
    with pytest.raises(ValueError, match=r"receipt|changed"):
        plan(candidate)


@pytest.mark.parametrize(
    "fault",
    (
        "different_owned15",
        "unavailable_chip",
        "missing_owned_receipt",
        "budget",
        "missing_goalkeeper",
        "retained_restriction",
    ),
)
def test_fixed_fifteen_original_inventory_and_policy_refusals(fault):
    case = native_case()
    ids, xi, bench, options = tuple(range(1, 16)), XI, BENCH, {}
    if fault == "missing_owned_receipt":
        case.resources.pop("owned")
    elif fault == "unavailable_chip":
        case.resources["chips"]["bboost"] = False
        options["chip"] = "bboost"
    elif fault == "budget":
        options["max_evaluations"] = 129
    elif fault == "different_owned15":
        # Same club and position keeps every other inventory constraint legal.
        ids = tuple(22 if p == 10 else p for p in ids)
        xi = tuple(22 if p == 10 else p for p in xi)
    elif fault == "missing_goalkeeper":
        ids = tuple(20 if p == 2 else p for p in ids)
        bench = tuple(20 if p == 2 else p for p in bench)
        case.resources["owned"] = list(ids)
    elif fault == "retained_restriction":
        case.resources["hit_points"] = 0
        options["hit_points"] = 4
    with pytest.raises((ValueError, EvaluationValidationError)):
        candidate = compose(case, enabled=False)
        plan(candidate, ids=ids, xi=xi, bench=bench, **options)


def test_fixed_fifteen_max_three_persistent_clubs_has_independent_inventory_oracle():
    case = native_case()
    ids = tuple(19 if p == 10 else p for p in range(1, 16))
    case.resources["owned"] = list(ids)
    candidate = compose(case, enabled=False)
    with pytest.raises(ValueError, match="three players"):
        plan(candidate, ids=ids, xi=tuple(19 if p == 10 else p for p in XI))


@pytest.mark.parametrize("fault", ("probability_mass", "changed_marginal", "wrong_input"))
def test_model_prediction_receipt_and_joint_marginal_refusals(model, monkeypatch, fault):
    case = native_case()
    weeks = case_inputs(case)
    original = model.predict

    def invalid(week, **options):
        result = original(week, **options)
        if fault == "probability_mass":
            return replace(result, probabilities=tuple(p * 0.5 for p in result.probabilities))
        if fault == "changed_marginal":
            return replace(result, fixture_probabilities=(LAW,))
        other = weeks[1] if week.player_code == 1 else week
        return replace(result, week=other)

    monkeypatch.setattr(model, "predict", invalid)
    with pytest.raises(ValueError):
        compose(case, model, weeks=weeks)


@pytest.mark.parametrize(
    "fault",
    (
        "basis",
        "position",
        "decision",
        "deadline",
        "fixture_kickoff",
        "fixture_home",
        "fixture_opponent",
        "fixture_law",
        "role_status",
    ),
)
def test_enabled_load_inputs_must_bind_the_same_native_capture(model, fault):
    case = native_case()
    weeks = list(case_inputs(case))
    first = weeks[0]
    assert (first.player_code, first.position, len(first.fixtures)) == (1, "GK", 1)
    message = "differs from the original native capture"
    if fault == "basis":
        weeks[0] = replace(first, native_basis_sha256="0" * 64)
    elif fault == "position":
        weeks[0] = replace(first, position="FWD")
    elif fault == "decision":
        weeks[0] = replace(
            first,
            decision_at="2026-09-22T11:00:00Z",
            interval_start_at="2026-08-25T11:00:00Z",
            interval_end_at="2026-09-22T11:00:00Z",
        )
    elif fault == "deadline":
        weeks[0] = replace(first, deadline_at="2026-09-22T17:00:00Z")
    elif fault.startswith("fixture_"):
        message = "different native fixture"
        fixture = first.fixtures[0]
        assert (fixture.club_code, fixture.opponent_code, fixture.is_home) == (1, 2, 1)
        probabilities = first.native_joint_probabilities
        if fault == "fixture_kickoff":
            fixture = replace(fixture, kickoff="2026-09-23T16:00:00Z")
        elif fault == "fixture_home":
            fixture = replace(fixture, is_home=0)
        elif fault == "fixture_opponent":
            fixture = replace(fixture, opponent_code=3)
        else:
            # The same weekly appearance with a different native role split.
            probabilities = (0.12, 0.10, 0.08, 0.45, 0.10, 0.10, 0.05)
            fixture = replace(fixture, probabilities=probabilities)
        weeks[0] = replace(
            first,
            fixtures=(fixture,),
            native_joint_probabilities=probabilities,
            native_joint_law_sha256=native_joint_law_digest(
                (fixture,), first.native_joint_states, probabilities
            ),
        )
    else:
        message = "starting-role support"
        case = unknown_role_case()
        basis = native_basis_digest(case.components)
        weeks = [replace(week, native_basis_sha256=basis) for week in weeks]
    with pytest.raises(ValueError, match=message):
        compose(case, model, weeks=tuple(weeks))


def test_native_components_cannot_be_scaled_twice_before_recipients(model):
    case = native_case()
    case.components.loc[case.components.club.eq(1), ["goals", "assists"]] = 2 / 11
    for index, row in case.components.iterrows():
        case.components.loc[index, list(score_row(row))] = list(score_row(row).values())
    case = served_again(case)
    heavy = tuple(p for p in case.roster.loc[case.roster.club_code.eq(1), "player_id"] if p != 1)
    with pytest.raises(ValueError, match="physical goal mass"):
        compose(case, model, weeks=case_inputs(case, heavy_players=heavy))


def test_all_competition_minutes_retain_extra_time_and_actual_rest_source_values():
    case = native_case()
    light = case_inputs(case)[0]
    loaded = case_inputs(case, heavy_players=(1,))[0]
    fields = dict(zip(loaded.feature_names, loaded.features, strict=True))
    light_fields = dict(zip(light.feature_names, light.features, strict=True))
    assert fields["player_physical_minutes_7d"] == 98 + 125 + 96
    assert fields["player_extra_time_minutes_7d"] == 30
    assert fields["player_added_minutes_7d"] == 8 + 5 + 6
    assert light_fields["player_physical_minutes_7d"] == 0
    assert fields["player_hours_since_last_recorded_exit"] < fields["player_kickoff_gap_hours"]
    assert fields["actual_travel_distance_km"] == 2200
    assert light_fields["actual_travel_distance_km"] == 0
    assert fields["planned_travel_distance_km"] is None


def test_original_source_bytes_are_required_in_addition_to_declared_joint_hash():
    case = native_case()
    document, fixtures, states, probabilities = next(iter(case_documents(case)))
    raw, sha = document_bytes(document)
    with pytest.raises(DataError, match="SHA256"):
        read_load_snapshot(
            raw + b" ",
            sha256=sha,
            season=SEASON,
            gameweek=6,
            player_code=1,
            decision_at=DECISION,
            deadline_at=DEADLINE,
            native_fixtures=fixtures,
            native_joint_states=states,
            native_joint_probabilities=probabilities,
            native_basis_sha256=document["native_basis_sha256"],
            required_competition_ids=("pl", "cup", "continental", "national"),
        )


def test_verified_empty_history_differs_from_missing_exposure_records():
    case = native_case()
    document, fixtures, states, probabilities = next(iter(case_documents(case)))
    missing = deepcopy(document)
    missing["matches"][0]["physical_minutes"] = None
    missing["matches"][0]["added_minutes"] = None
    missing["matches"][0]["extra_time_minutes"] = None
    missing["matches"][0]["recorded_exit_at"] = None
    known = parse_workload(document, fixtures, states, probabilities)
    unknown = parse_workload(missing, fixtures, states, probabilities)
    one = dict(zip(known.feature_names, known.features, strict=True))
    two = dict(zip(unknown.feature_names, unknown.features, strict=True))
    assert one["player_missing_minutes_count_28d"] == 0
    assert two["player_missing_minutes_count_28d"] == 1
    assert two["player_physical_minutes_28d"] is None
    empty = deepcopy(document)
    empty["matches"] = []
    empty["club_matches"] = []
    empty["coverage"]["expected_match_ids"] = []
    empty["coverage"]["expected_club_match_ids"] = []
    zero = parse_workload(empty, fixtures, states, probabilities)
    values = dict(zip(zero.feature_names, zero.features, strict=True))
    assert values["player_physical_minutes_28d"] == 0
    assert values["player_missing_minutes_count_28d"] == 0
    assert values["player_hours_since_last_recorded_exit"] is None


def test_equivalent_offset_clocks_and_row_order_preserve_features_and_predictions(model):
    case = native_case()
    document, fixtures, states, probabilities = next(iter(case_documents(case, heavy_players=(1,))))
    original = parse_workload(document, fixtures, states, probabilities)
    shifted = deepcopy(document)

    def offsets(value):
        if isinstance(value, dict):
            return {key: offsets(item) for key, item in value.items()}
        if isinstance(value, list):
            return [offsets(item) for item in value]
        if (
            isinstance(value, str)
            and "T" in value
            and (value.endswith("Z") or value.endswith("+00:00"))
        ):
            return pd.Timestamp(value).tz_convert("Europe/Istanbul").isoformat()
        return value

    shifted = offsets(shifted)
    shifted["matches"].reverse()
    shifted["club_matches"].reverse()
    equivalent = parse_workload(shifted, fixtures, states, probabilities)
    assert equivalent.features == original.features
    assert model.predict(equivalent).probabilities == model.predict(original).probabilities
    assert equivalent.source_sha256 != original.source_sha256


def test_prepared_native_four_bin_control_stays_available_without_role_source():
    case = native_case()
    frame = case.components.copy(deep=True)
    for index, row in frame.iterrows():
        p = (*(float(row[f"minute_probability_{i}"]) for i in range(4)), 0.0, 0.0, 0.0)
        m = (*(float(row[f"minute_value_{i}"]) for i in range(4)), 10.0, 65.0, 90.0)
        values = score_row(row, p, m)
        frame.loc[index, list(values)] = list(values.values())
    frame["model_version"] = FOOTBALL_MODEL_VERSION
    frame.attrs["joint_role"] = False
    case = served_again(replace(case, components=frame))
    candidate = compose(case, enabled=False)
    assert_unmarked_equal(candidate.components, frame)
    assert_unmarked_equal(candidate.weekly, case.weekly)


def test_disabled_preserves_dependent_dgw_served_values_without_workload_or_model():
    case = native_case(double=True)
    case.weekly.loc[case.weekly.player_id.eq(3), "appearance_probability"] = 0.75 * 0.88
    # These sentinels must remain unopened, because disabled is the captured control.
    candidate = compose(case, object(), weeks=object(), enabled=False)
    assert_unmarked_equal(candidate.components, case.components)
    assert_unmarked_equal(candidate.weekly, case.weekly)
    assert json.loads(candidate.receipt_json)["native_joint_input_sha256"] == []


def test_zero_attacking_channels_and_structural_endpoints_have_no_invented_support(model):
    case = native_case()
    case.components.loc[case.components.club.isin((1, 2)), ["goals", "assists"]] = 0.0
    for pid, law in (
        (1, (1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)),
        (3, (0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)),
    ):
        for index, row in case.components.loc[case.components.player_code.eq(pid)].iterrows():
            values = score_row(row, law)
            case.components.loc[index, list(values)] = list(values.values())
            if pid == 1:
                case.components.loc[index, ["goals_share", "assists_share"]] = 0
    club_one = case.components.club.eq(1) & case.components.player_code.ne(1)
    case.components.loc[club_one, ["goals_share", "assists_share"]] = 0.1
    for index, row in case.components.iterrows():
        probabilities = (
            row.zero_probability,
            *(
                row[f"{role}_minute_probability_{b}"]
                for role in ("start", "cameo")
                for b in (1, 2, 3)
            ),
        )
        values = score_row(row, probabilities)
        case.components.loc[index, list(values)] = list(values.values())
    case = served_again(case)
    candidate = compose(case, model)
    one = candidate.components.loc[candidate.components.player_code.eq(1)].iloc[0]
    three = candidate.components.loc[candidate.components.player_code.eq(3)].iloc[0]
    assert one.appearance_probability == 0
    assert one.expected_minutes == 0
    assert one.expected_points == 0
    assert three.appearance_probability == 1
    assert three.expected_minutes == 90
    assert candidate.components.loc[candidate.components.club.isin((1, 2)), "goals"].eq(0).all()
    assert candidate.components.loc[candidate.components.club.isin((1, 2)), "assists"].eq(0).all()
    assert (
        candidate.components.loc[candidate.components.player_code.eq(1), "goals_share"].eq(0).all()
    )


@pytest.mark.parametrize("missing", (None, pd.NA, math.nan), ids=("null", "pandas_na", "nan"))
def test_unknown_native_start_roles_remain_exact_disabled_control(missing):
    case = unknown_role_case(missing)
    frame = case.components
    candidate = compose(case, object(), weeks=object(), enabled=False)
    assert_unmarked_equal(candidate.components, frame)
    assert_unmarked_equal(candidate.weekly, case.weekly)
    choice = plan(candidate, max_evaluations=1, locked_first=True)
    assert set(choice.squad.player_id) == set(range(1, 16))
    replacement = math.nan if missing is None else None
    candidate.components.loc[0, "start_probability"] = replacement
    with pytest.raises(ValueError, match="changed"):
        plan(candidate, max_evaluations=1, locked_first=True)
