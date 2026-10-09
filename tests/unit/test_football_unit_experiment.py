"""Private synthetic source-to-fixture-to-weekly-to-fixed-fifteen checks."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, replace
from datetime import timedelta
from types import MappingProxyType

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_football_unit_strength import T, observations, projection, unit

from squadopt.application.football_unit_experiment import (
    UNIT_COMPONENT_VERSION,
    unit_fixed_fifteen_decision,
    unit_fixture_components,
    unit_weekly_forecast,
)
from squadopt.features.football_fm_attributes import read_fm_attributes
from squadopt.features.football_unit_catalog import read_unit_observations, read_unit_projection
from squadopt.features.football_unit_inputs import (
    UNIT_INPUT_VERSION,
    NumericAttributeSpec,
    ProjectedUnitState,
)
from squadopt.live.minute_evidence import _score_components
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION
from squadopt.prediction.football_unit_strength import FootballUnitStrengthModel


def document(kind, value):
    def normalize(obj):
        if isinstance(obj, dict):
            return {k: (dict(v) if k == "values" else normalize(v)) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [normalize(x) for x in obj]
        return obj

    return json.dumps(
        {"version": UNIT_INPUT_VERSION, "kind": kind, kind: normalize(value)},
        default=lambda x: x.isoformat(),
    ).encode()


@pytest.fixture(scope="module")
def experiment():
    training = read_unit_observations(document("observations", [asdict(o) for o in observations()]))
    model = FootballUnitStrengthModel(training, cutoff=T + timedelta(days=50))
    p = projection()
    p = replace(
        p,
        states=(
            ProjectedUnitState(0.75, unit(1, replacement=True), unit(2)),
            ProjectedUnitState(0.25, unit(1), unit(2, replacement=True)),
        ),
    )
    parsed = read_unit_projection(document("projection", asdict(p)))
    return model, parsed, model.predict(parsed)


def baseline(p):
    records = []
    for club, offset, home, rate, opposing in (
        (1, 0, 1, p.causal_baseline_own_goal_rate, p.causal_baseline_opponent_goal_rate),
        (2, 100, 0, p.causal_baseline_opponent_goal_rate, p.causal_baseline_own_goal_rate),
    ):
        positions = ["GK"] + ["DEF"] * 4 + ["MID"] * 4 + ["FWD"] * 3
        for i, pos in enumerate(positions, 1):
            records.append(
                {
                    "GW": p.gameweek,
                    "fixture": p.fixture_id,
                    "kickoff": p.kickoff.isoformat(),
                    "club": club,
                    "opponent": 3 - club,
                    "home": home,
                    "player_code": offset + i,
                    "position": pos,
                    "model_version": FOOTBALL_MODEL_VERSION,
                    "team_goal_rate": rate,
                    "opponent_goal_rate": opposing,
                    "goals": rate / 12,
                    "assists": rate * 0.7 / 12,
                    "goals_share": 1 / 12,
                    "assists_share": 1 / 12,
                    "defcon_rate90": 5,
                    "defcon_dispersion": 2,
                    "residual_if_appearance": 0.4,
                    "minute_probability_0": 0.2,
                    "minute_probability_1": 0.1,
                    "minute_probability_2": 0.2,
                    "minute_probability_3": 0.5,
                    "minute_value_0": 0,
                    "minute_value_1": 20,
                    "minute_value_2": 70,
                    "minute_value_3": 90,
                }
            )
    frame = pd.DataFrame(records)
    frame.attrs["season"] = p.season
    return _score_components(frame)


def roster():
    return pd.DataFrame(
        {
            "player_id": [1, 101, 2, 102, 201, 202, 203, 6, 204, 205, 206, 207, 110, 208, 209],
            "position": ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3,
            "club": [1, 2, 1, 2, 3, 3, 3, 1, 4, 4, 4, 5, 2, 5, 5],
            "purchase_price": [50] * 15,
            "selling_price": [48] * 15,
        }
    )


XI = (1, 2, 102, 201, 6, 204, 205, 206, 110, 208, 209)
BENCH = (101, 202, 203, 207)


def calendar(rows):
    return rows[["GW", "fixture", "club"]].drop_duplicates().reset_index(drop=True)


def test_source_to_frozen_decision_and_independent_scoring_algebra(experiment):
    _, p, result = experiment
    native = baseline(p)
    before = native.copy(deep=True)
    components = unit_fixture_components(native, [result], season=p.season)
    assert_frame_equal(native, before)
    assert components.attrs["component_version"] == UNIT_COMPONENT_VERSION
    assert set(components.model_version) == {result.model_version}
    for club, side in components.groupby("club"):
        mean = result.own_goal_rate if club == 1 else result.opponent_goal_rate
        assert side.goals.sum() == pytest.approx(mean)
        assert side.assists.sum() == pytest.approx(0.7 * mean)
        state_clean = math.fsum(
            s.probability
            * (
                0.2 * math.exp(-(s.opponent_goal_rate if club == 1 else s.own_goal_rate) * 70 / 90)
                + 0.5 * math.exp(-(s.opponent_goal_rate if club == 1 else s.own_goal_rate))
            )
            for s in result.state_rates
        )
        assert side.clean_sheet_probability.to_numpy() == pytest.approx(state_clean)
        for row in side.itertuples():
            goal = {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}[row.position]
            cs = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}[row.position]
            raw = 0.8 + 0.7 + goal * row.goals + 3 * row.assists + cs * state_clean + 0.8 * 0.4
            assert row.raw_expected_points == pytest.approx(raw)
    fixed = roster()
    saved = fixed.copy(deep=True)
    a = dict.fromkeys(fixed.player_id, 1.0)
    a[2] = 0.75
    weekly = unit_weekly_forecast(
        fixed, components, calendar(components), gameweek=8, eligibility=a
    )
    assert weekly.loc[weekly.player_id.eq(2), "appearance_probability"].item() == pytest.approx(0.6)
    assert_frame_equal(fixed, saved)
    for resource in ("purchase_price", "selling_price", "club", "position", "player_id"):
        assert weekly[resource].equals(saved[resource])
    selected = unit_fixed_fifteen_decision(weekly, XI, BENCH, 110, 6, max_evaluations=32)
    assert selected.best.expected_net_points >= selected.incumbent.expected_net_points
    assert set(selected.best.starting_xi) | set(selected.best.ordered_bench) == set(fixed.player_id)
    assert selected.proof_scope == "bounded_fixed_squad_neighborhood_only"
    assert selected.evaluations <= 32


def test_nonlinear_clean_sheet_mixture_cannot_be_replaced_by_mean_rate(experiment):
    _, p, result = experiment
    components = unit_fixture_components(baseline(p), [result], season=p.season)
    away = components.loc[components.club.eq(2)].iloc[0]
    wrong = 0.2 * math.exp(-result.own_goal_rate * 70 / 90) + 0.5 * math.exp(-result.own_goal_rate)
    assert away.clean_sheet_probability > wrong + 1e-5


def test_reference_identity_retains_native_components(experiment):
    model, p, _ = experiment
    neutral = replace(p, states=(ProjectedUnitState(1.0, unit(1), unit(2)),))
    native = baseline(neutral)
    out = unit_fixture_components(native, [model.predict(neutral)], season=neutral.season)
    assert_frame_equal(
        native.drop(columns="model_version"),
        out.drop(columns="model_version"),
        check_exact=False,
        rtol=1e-14,
        atol=1e-14,
        check_flags=False,
    )


@pytest.mark.parametrize("eligibility", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_double_week_shared_eligibility_once_and_explicit_blanks(experiment, eligibility):
    model, p, result = experiment
    second = replace(
        p,
        fixture_id=80,
        catalog=replace(p.catalog, fixture_id=80),
        kickoff=p.kickoff + timedelta(days=3),
    )
    native = pd.concat([baseline(p), baseline(second)], ignore_index=True)
    components = unit_fixture_components(native, [result, model.predict(second)], season=p.season)
    fixed = roster()
    a = dict.fromkeys(fixed.player_id, 1.0)
    a[2] = eligibility
    weekly = unit_weekly_forecast(
        fixed, components, calendar(components), gameweek=8, eligibility=a
    )
    player = weekly.loc[weekly.player_id.eq(2)].iloc[0]
    assert player.appearance_probability == pytest.approx(eligibility * (1 - 0.2**2))
    assert player.expected_points == pytest.approx(
        eligibility * components.loc[components.player_code.eq(2), "expected_points"].sum()
    )
    blank = weekly.loc[weekly.player_id.ge(200)]
    assert (blank.expected_points == 0).all() and (blank.appearance_probability == 0).all()


@pytest.mark.parametrize("chip", [None, "3xc", "bboost", "wildcard", "freehit"])
def test_native_locks_chips_hits_and_roster_resources(experiment, chip):
    _, p, result = experiment
    components = unit_fixture_components(baseline(p), [result], season=p.season)
    weekly = unit_weekly_forecast(
        roster(),
        components,
        calendar(components),
        gameweek=8,
        eligibility=dict.fromkeys(roster().player_id, 1.0),
    )
    snapshot = weekly.copy(deep=True)
    selected = unit_fixed_fifteen_decision(
        weekly, XI, BENCH, 110, 6, chip=chip, hit_points=4, locked_first=True
    )
    assert selected.evaluations == 1
    assert selected.best.starting_xi == XI and selected.best.ordered_bench == BENCH
    assert selected.best.captain_id == 110 and selected.best.vice_captain_id == 6
    assert selected.best.chip == chip and selected.best.hit_points == 4
    assert_frame_equal(weekly, snapshot)


@pytest.mark.parametrize(
    "damage",
    [
        lambda r: replace(r, season="2023-24"),
        lambda r: replace(r, gameweek=9),
        lambda r: replace(r, club=3),
        lambda r: replace(r, home=False),
        lambda r: replace(r, kickoff=r.kickoff + timedelta(hours=1)),
        lambda r: replace(r, decision_cutoff=r.kickoff),
        lambda r: replace(r, causal_baseline_own_goal_rate=2.0),
        lambda r: replace(r, state_rates=()),
        lambda r: replace(r, own_goal_rate=r.own_goal_rate + 1),
        lambda r: replace(r, state_rates=(replace(r.state_rates[0], probability=0.4),)),
        lambda r: replace(r, state_rates=(replace(r.state_rates[0], own_goal_rate=np.inf),)),
        lambda r: replace(r, model_version=FOOTBALL_MODEL_VERSION),
    ],
)
def test_unit_result_basis_mismatch_refuses(experiment, damage):
    _, p, result = experiment
    with pytest.raises(ValueError):
        unit_fixture_components(baseline(p), [damage(result)], season=p.season)


@pytest.mark.parametrize(
    "results", [lambda r: [], lambda r: [r, r], lambda r: [r, replace(r, fixture_id=99)]]
)
def test_exact_fixture_result_coverage_required(experiment, results):
    _, p, result = experiment
    with pytest.raises(ValueError):
        unit_fixture_components(baseline(p), results(result), season=p.season)


def test_missing_scheduled_row_is_not_a_blank(experiment):
    _, p, result = experiment
    components = unit_fixture_components(baseline(p), [result], season=p.season)
    missing = components.loc[~components.player_code.eq(2)].copy()
    with pytest.raises(ValueError, match="complete player-fixture"):
        unit_weekly_forecast(
            roster(),
            missing,
            calendar(components),
            gameweek=8,
            eligibility=dict.fromkeys(roster().player_id, 1.0),
        )


def test_scheduled_unknown_roster_player_is_not_a_blank(experiment):
    _, p, result = experiment
    components = unit_fixture_components(baseline(p), [result], season=p.season)
    fixed = roster()
    fixed.loc[fixed.player_id.eq(2), "player_id"] = 999
    with pytest.raises(ValueError, match="complete player-fixture"):
        unit_weekly_forecast(
            fixed,
            components,
            calendar(components),
            gameweek=8,
            eligibility=dict.fromkeys(fixed.player_id, 1.0),
        )


@pytest.mark.parametrize("value", [-0.1, 1.1, np.nan, np.inf, True, "0.75"])
def test_invalid_eligibility_refuses(experiment, value):
    _, p, result = experiment
    components = unit_fixture_components(baseline(p), [result], season=p.season)
    a = dict.fromkeys(roster().player_id, 1.0)
    a[2] = value
    with pytest.raises(ValueError):
        unit_weekly_forecast(roster(), components, calendar(components), gameweek=8, eligibility=a)


def test_learned_unit_changes_keeper_choice_against_independent_role_oracle(experiment):
    model, p, _ = experiment
    p = replace(p, causal_baseline_own_goal_rate=0.8, causal_baseline_opponent_goal_rate=1.4)
    neutral = replace(p, states=(ProjectedUnitState(1, unit(1), unit(2)),))
    changed = replace(p, states=(ProjectedUnitState(1, unit(1, replacement=True), unit(2)),))
    outcomes = []
    for projected in (neutral, changed):
        components = unit_fixture_components(
            baseline(projected), [model.predict(projected)], season=p.season
        )
        weekly = unit_weekly_forecast(
            roster(),
            components,
            calendar(components),
            gameweek=8,
            eligibility=dict.fromkeys(roster().player_id, 1.0),
        )
        starting = tuple(101 if x == 1 else x for x in XI)
        selected = unit_fixed_fifteen_decision(
            weekly, starting, (1, *BENCH[1:]), 110, 6, max_evaluations=128
        )
        means = weekly.set_index("player_id").expected_points
        # With q=.8 for both keepers, the independent keeper contribution is
        # mu_start + (1-q_start)*mu_reserve. No role-search code is used here.
        oracle = max((1, 101), key=lambda keeper: means[keeper] + 0.2 * means[102 - keeper])
        actual = next(x for x in selected.best.starting_xi if x in (1, 101))
        assert actual == oracle
        outcomes.append(actual)
    assert outcomes == [101, 1]


def test_dgw_postdeadline_second_projection_refuses(experiment):
    model, p, first = experiment
    second = replace(
        p,
        fixture_id=80,
        catalog=replace(p.catalog, fixture_id=80),
        kickoff=p.kickoff + timedelta(days=3),
    )
    late = replace(model.predict(second), decision_cutoff=p.decision_cutoff + timedelta(days=1))
    with pytest.raises(ValueError, match="common decision cutoff"):
        unit_fixture_components(
            pd.concat([baseline(p), baseline(second)], ignore_index=True),
            [first, late],
            season=p.season,
        )


@pytest.mark.parametrize(
    "field,value",
    [
        ("input_version", "wrong"),
        ("feature_version", "wrong"),
        ("feature_columns", ()),
        ("training_cutoff", "2040-01-01T00:00:00+00:00"),
        ("training_cutoff", "invalid"),
        ("training_rows", True),
        ("training_catalog_sha256", ()),
        ("projection_source_receipts", ()),
        ("training_source_receipts", ((1,),)),
        ("projection_catalog_sha256", "bad"),
        ("baseline_source_id", "missing"),
    ],
)
def test_invalid_model_provenance_refuses(experiment, field, value):
    _, p, result = experiment
    bad = replace(result, metadata=MappingProxyType({**result.metadata, field: value}))
    with pytest.raises(ValueError):
        unit_fixture_components(baseline(p), [bad], season=p.season)


@pytest.mark.parametrize(
    "column", ["expected_points", "raw_expected_points", "clean_sheet_probability", "model_version"]
)
def test_mutated_private_component_basis_refuses(experiment, column):
    _, p, result = experiment
    components = unit_fixture_components(baseline(p), [result], season=p.season)
    components.loc[0, column] = "wrong" if column == "model_version" else 0.123
    with pytest.raises(ValueError, match="receipts changed"):
        unit_weekly_forecast(
            roster(),
            components,
            calendar(components),
            gameweek=8,
            eligibility=dict.fromkeys(roster().player_id, 1.0),
        )


def test_boolean_eligibility_identity_refuses(experiment):
    _, p, result = experiment
    components = unit_fixture_components(baseline(p), [result], season=p.season)
    a = dict.fromkeys(roster().player_id, 1.0)
    del a[1]
    a[True] = 1.0
    with pytest.raises(ValueError, match="positive integers"):
        unit_weekly_forecast(roster(), components, calendar(components), gameweek=8, eligibility=a)


@pytest.mark.parametrize("column", ["expected_points", "purchase_price"])
def test_weekly_forecast_or_resources_changed_before_decision_refuses(experiment, column):
    _, p, result = experiment
    components = unit_fixture_components(baseline(p), [result], season=p.season)
    weekly = unit_weekly_forecast(
        roster(),
        components,
        calendar(components),
        gameweek=8,
        eligibility=dict.fromkeys(roster().player_id, 1.0),
    )
    weekly.loc[0, column] += 1
    with pytest.raises(ValueError, match="provenance changed"):
        unit_fixed_fifteen_decision(weekly, XI, BENCH, 110, 6)


def test_unsupported_gameweek_cannot_be_silently_declared_blank(experiment):
    _, p, result = experiment
    components = unit_fixture_components(baseline(p), [result], season=p.season)
    with pytest.raises(ValueError, match="declared decision cutoff"):
        unit_weekly_forecast(
            roster(),
            components,
            calendar(components),
            gameweek=9,
            eligibility=dict.fromkeys(roster().player_id, 1.0),
        )


@pytest.mark.parametrize("field", ["projection_sha256", "reference_unit_identity"])
def test_full_projection_reference_receipt_required(experiment, field):
    _, p, result = experiment
    metadata = dict(result.metadata)
    del metadata[field]
    with pytest.raises(ValueError):
        unit_fixture_components(
            baseline(p), [replace(result, metadata=MappingProxyType(metadata))], season=p.season
        )


@pytest.mark.parametrize("field", ["decision_cutoff", "kickoff"])
def test_unit_result_naive_time_refuses_at_boundary(experiment, field):
    _, p, result = experiment
    bad = replace(result, **{field: getattr(result, field).replace(tzinfo=None)})
    with pytest.raises(ValueError, match="explicit timezone"):
        unit_fixture_components(baseline(p), [bad], season=p.season)


def test_weekly_provenance_change_before_decision_refuses(experiment):
    _, p, result = experiment
    components = unit_fixture_components(baseline(p), [result], season=p.season)
    weekly = unit_weekly_forecast(
        roster(),
        components,
        calendar(components),
        gameweek=8,
        eligibility=dict.fromkeys(roster().player_id, 1.0),
    )
    weekly.attrs["decision_cutoffs"] = ((8, p.decision_cutoff + timedelta(days=1)),)
    with pytest.raises(ValueError, match="provenance changed"):
        unit_fixed_fifteen_decision(weekly, XI, BENCH, 110, 6)


def test_synthetic_fm_csv_crosswalk_to_model_fixture_weekly_and_roles():
    def captured(c):
        ids = sorted({m.player_id for m in c.mappings})
        raw = (
            ",UID,Hea\n"
            + "".join(f"{i},{10000 + p},{19 if p in (12, 112) else 8}\n" for i, p in enumerate(ids))
        ).encode()
        receipt = replace(
            c.sources[0],
            source_id="fm-fixture",
            provider="fictional-fm",
            version="FM23-synthetic-only",
            kind="fm",
            sha256=hashlib.sha256(raw).hexdigest(),
            rights_reference="fictional-fixture-model-license",
        )
        definitions = (
            NumericAttributeSpec(
                "heading", "fm-fixture", 1, 20, "rating", "Synthetic exact heading rating"
            ),
        )
        values = read_fm_attributes(
            raw,
            source=receipt,
            cutoff=c.decision_cutoff,
            attributes=definitions,
            attribute_columns={"heading": "Hea"},
            uid_column="UID",
            allow_unnamed_index=True,
        )
        crosswalk = tuple(
            replace(m, source_id="fm-fixture", source_player_id=str(10000 + m.player_id))
            for m in c.mappings
        )
        return replace(
            c,
            sources=(*c.sources, receipt),
            attributes=definitions,
            mappings=crosswalk,
            player_attributes=values,
        )

    historical = tuple(replace(o, catalog=captured(o.catalog)) for o in observations())
    model = FootballUnitStrengthModel(historical, cutoff=T + timedelta(days=50))
    p = projection()
    p = replace(p, catalog=captured(p.catalog))
    result = model.predict(p)
    assert result.own_replacement_gap > 0
    components = unit_fixture_components(baseline(p), [result], season=p.season)
    a = dict.fromkeys(roster().player_id, 1.0)
    a[2] = 0.75
    weekly = unit_weekly_forecast(
        roster(), components, calendar(components), gameweek=8, eligibility=a
    )
    assert weekly.loc[weekly.player_id.eq(2), "appearance_probability"].item() == pytest.approx(0.6)
    selected = unit_fixed_fifteen_decision(weekly, XI, BENCH, 110, 6, max_evaluations=16)
    assert selected.best.expected_net_points >= selected.incumbent.expected_net_points
    assert set(weekly.player_id) == set(roster().player_id)
