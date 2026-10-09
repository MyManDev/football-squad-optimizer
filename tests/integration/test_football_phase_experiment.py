"""Invented raw duties through learned counts, weekly eligibility and official autosubs."""

import json
import math
from itertools import product

import pandas as pd
import pytest
from tests.football_phase_fixtures import (
    BENCH,
    DECISION,
    XI,
    fitted_model,
    native_case,
    projection_document,
    read_projection,
)

from squadopt.application.football_phase_experiment import (
    phase_fixed_fifteen_decision,
    phase_fixture_components,
    phase_weekly_forecast,
)
from squadopt.evaluation.models import FrozenSquadDecision
from squadopt.evaluation.scoring import score_frozen_squad_decision
from squadopt.prediction.football import FOOTBALL_MODEL_VERSION


@pytest.fixture(scope="module")
def model():
    return fitted_model()


def _projections(native, *, changed=False, fixture=63):
    projections = []
    for current_fixture, club in native.groupby(["fixture", "club"]).groups:
        different = changed and current_fixture == fixture and club == 6
        projections.append(
            read_projection(
                projection_document(native, fixture=int(current_fixture), club=int(club)),
                penalty=12 if different else 18,
                delivery=6 if different else 24,
            )
        )
    return tuple(projections)


def _adjusted(native, model, *, changed=False, fixture=63, enabled=True):
    return phase_fixture_components(
        native,
        _projections(native, changed=changed, fixture=fixture),
        model,
        season="2026-27",
        enabled=enabled,
    )


def test_native_components_without_decision_column_use_explicit_original_cutoff(model):
    native, roster, calendar = native_case(dgw=True)
    projections = _projections(native, changed=True)
    columnless = native.drop(columns="decision_at")
    adjusted = phase_fixture_components(
        columnless, projections, model, season="2026-27", decision_at=DECISION
    )
    reference = _adjusted(native, model, changed=True)
    assert "decision_at" not in adjusted
    pd.testing.assert_frame_equal(adjusted, reference.drop(columns="decision_at"), check_exact=True)
    document = json.loads(adjusted.attrs["phase_receipt_json"])
    assert document["decision_at"] == DECISION
    weekly = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=6, eligibility=_eligibility(**{"6": 0.75})
    )
    expected = phase_weekly_forecast(
        roster, reference, calendar, gameweek=6, eligibility=_eligibility(**{"6": 0.75})
    )
    pd.testing.assert_frame_equal(weekly, expected, check_exact=True)
    decision = phase_fixed_fifteen_decision(weekly, XI, BENCH, 13, 8)
    expected_decision = phase_fixed_fifteen_decision(expected, XI, BENCH, 13, 8)
    assert decision.best == expected_decision.best
    assert decision.best.expected_net_points == pytest.approx(
        _official_expectation(weekly, decision.best), abs=1e-10
    )


def test_missing_native_decision_column_requires_explicit_cutoff(model):
    native, _, _ = native_case()
    with pytest.raises(ValueError, match="explicit decision cutoff"):
        phase_fixture_components(
            native.drop(columns="decision_at"), _projections(native), model, season="2026-27"
        )


def test_columnless_projection_cannot_replace_explicit_original_cutoff(model):
    native, _, _ = native_case()
    with pytest.raises(ValueError, match="explicit native decision cutoff"):
        phase_fixture_components(
            native.drop(columns="decision_at"),
            _projections(native),
            model,
            season="2026-27",
            decision_at="2026-09-22T11:59:59Z",
        )


def test_optional_native_decision_column_remains_binding(model):
    native, _, _ = native_case()
    projections = _projections(native)
    native.loc[native.index[0], "decision_at"] = "2026-09-22T11:59:59Z"
    with pytest.raises(ValueError, match="column differs from the explicit decision"):
        phase_fixture_components(native, projections, model, season="2026-27", decision_at=DECISION)


def test_equivalent_explicit_native_clock_preserves_canonical_receipt(model):
    native, _, _ = native_case()
    adjusted = phase_fixture_components(
        native,
        _projections(native),
        model,
        season="2026-27",
        decision_at="2026-09-22T12:00:00+00:00",
    )
    assert json.loads(adjusted.attrs["phase_receipt_json"])["decision_at"] == DECISION


@pytest.mark.parametrize("season", [None, "2026", "2026-99", "26-27", "abcd-ef", "2025-26"])
def test_enabled_fixture_adapter_requires_full_consecutive_admitted_season(model, season):
    native, _, _ = native_case()
    with pytest.raises(ValueError, match="season"):
        phase_fixture_components(native, _projections(native), model, season=season)


def test_columnless_weekly_calendar_still_binds_original_projection_clock(model):
    native, roster, calendar = native_case()
    adjusted = phase_fixture_components(
        native.drop(columns="decision_at"),
        _projections(native),
        model,
        season="2026-27",
        decision_at=DECISION,
    )
    calendar["decision_at"] = "2026-09-22T12:00:01Z"
    with pytest.raises(ValueError, match="recorded decision"):
        phase_weekly_forecast(roster, adjusted, calendar, gameweek=6, eligibility=_eligibility())


def _eligibility(**overrides):
    values = dict.fromkeys(range(1, 16), 1.0)
    values.update({int(key): value for key, value in overrides.items()})
    return values


def _official_expectation(weekly, action, *, chip=None, hit_points=0):
    """Enumerate outcome states through the accepted official rules, independently."""
    frame = weekly.set_index("player_id")
    uncertain = [code for code in frame.index if 0 < frame.at[code, "appearance_probability"] < 1]
    frozen = FrozenSquadDecision(
        weekly, action.starting_xi, action.ordered_bench, action.captain_id, action.vice_captain_id
    )
    terms = []
    for bits in product((False, True), repeat=len(uncertain)):
        appeared = {code: frame.at[code, "appearance_probability"] == 1 for code in frame.index}
        appeared.update(zip(uncertain, bits, strict=True))
        mass = math.prod(
            frame.at[code, "appearance_probability"]
            if appeared[code]
            else 1 - frame.at[code, "appearance_probability"]
            for code in uncertain
        )
        outcomes = pd.DataFrame(
            {
                "player_id": frame.index,
                "minutes": [int(appeared[code]) for code in frame.index],
                "total_points": [
                    frame.at[code, "expected_points"] / frame.at[code, "appearance_probability"]
                    if appeared[code]
                    else 0.0
                    for code in frame.index
                ],
            }
        )
        score = score_frozen_squad_decision(frozen, outcomes)
        gross = score.total_points
        if chip == "3xc":
            gross += score.captain_bonus_points
        elif chip == "bboost":
            gross = float(outcomes.total_points.sum()) + score.captain_bonus_points
        terms.append(mass * (gross - hit_points))
    return math.fsum(terms)


def _native_points(row):
    """Direct FPL component algebra, without calling the producer recomputation."""
    goal = {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}[row.position]
    clean = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}[row.position]
    return (
        row.appearance_probability
        + row.p60
        + goal * row.goals
        + 3 * row.assists
        + clean * row.clean_sheet_probability
        + 2 * row.defcon_probability
        + row.appearance_probability * row.residual_if_appearance
    )


def test_captured_duty_change_reaches_legal_xi_captain_and_ordered_reserves(model):
    native, roster, calendar = native_case()
    saved_native, saved_roster, saved_calendar = (
        frame.copy(deep=True) for frame in (native, roster, calendar)
    )
    old = _adjusted(native, model)
    new = _adjusted(native, model, changed=True)
    eligibility = _eligibility(**{"6": 0.75, "13": 0.75})
    before = phase_weekly_forecast(roster, old, calendar, gameweek=6, eligibility=eligibility)
    after = phase_weekly_forecast(roster, new, calendar, gameweek=6, eligibility=eligibility)
    original = phase_fixed_fifteen_decision(before, XI, BENCH, 13, 8)
    improved = phase_fixed_fifteen_decision(after, XI, BENCH, 13, 8)
    assert 12 not in original.best.starting_xi
    assert original.best.captain_id == 13
    assert original.best.ordered_bench[1] == 7
    assert set(improved.best.starting_xi) == (set(XI) - {11}) | {12}
    assert improved.best.captain_id == 12
    assert improved.best.ordered_bench == (2, 6, 11, 7)
    assert improved.best.expected_net_points > original.best.expected_net_points
    assert improved.best.expected_net_points == pytest.approx(
        _official_expectation(after, improved.best), abs=1e-11
    )
    assert original.best.expected_net_points == pytest.approx(
        _official_expectation(before, original.best), abs=1e-11
    )
    assert improved.proof_scope == "bounded_fixed_squad_neighborhood_only"
    assert improved.evaluations <= 128
    for result in (before, after):
        assert set(result.player_id) == set(range(1, 16))
        pd.testing.assert_frame_equal(result[roster.columns], roster, check_exact=True)
        assert result.attrs["bank_tenths"] == 17
        assert result.attrs["free_transfers"] == 2
        assert result.attrs["chip"] is None
        assert result.attrs["hit_points"] == 0
        assert result.attrs["transfer_policy"] == {"inventory": "fixed", "budget": "retain"}
    pd.testing.assert_frame_equal(native, saved_native, check_exact=True)
    pd.testing.assert_frame_equal(roster, saved_roster, check_exact=True)
    pd.testing.assert_frame_equal(calendar, saved_calendar, check_exact=True)


def test_allocation_conserves_native_counts_and_changes_only_attacking_points(model):
    native, _, _ = native_case()
    adjusted = _adjusted(native, model, changed=True)
    excluded = {
        "goals",
        "assists",
        "goals_share",
        "assists_share",
        "raw_expected_points",
        "expected_points",
        "model_version",
    }
    unchanged = [column for column in native if column not in excluded]
    pd.testing.assert_frame_equal(adjusted[unchanged], native[unchanged], check_exact=True)
    for keys, old in native.groupby(["GW", "fixture", "club"]):
        new = adjusted.loc[
            adjusted.GW.eq(keys[0]) & adjusted.fixture.eq(keys[1]) & adjusted.club.eq(keys[2])
        ]
        for head in ("goals", "assists"):
            assert new[head].sum() == pytest.approx(old[head].sum(), abs=1e-12)
            assert new[head + "_share"].sum() == pytest.approx(1.0, abs=1e-12)
    for row in adjusted.itertuples():
        raw = _native_points(row)
        assert row.raw_expected_points == pytest.approx(raw, abs=1e-12)
        assert row.expected_points == max(row.raw_expected_points, 0.0)
    assert native.model_version.eq(FOOTBALL_MODEL_VERSION).all()
    assert not adjusted.model_version.eq(FOOTBALL_MODEL_VERSION).all()


@pytest.mark.parametrize("change", ["penalty", "delivery"])
def test_scoring_and_delivery_capture_changes_have_distinct_learned_heads(model, change):
    native, _, _ = native_case()
    document = projection_document(native)
    old = read_projection(document)
    new = read_projection(
        document,
        penalty=12 if change == "penalty" else 18,
        delivery=6 if change == "delivery" else 24,
    )
    first = model.predict(old)
    second = model.predict(new)
    before = {row.player_code: row for row in first.players}
    after = {row.player_code: row for row in second.players}
    if change == "penalty":
        assert after[12].goals > before[12].goals
        assert after[18].goals < before[18].goals
        assert [row.assists for row in first.players] == [row.assists for row in second.players]
    else:
        assert after[6].assists > before[6].assists
        assert after[24].assists < before[24].assists
        assert [row.goals for row in first.players] == [row.goals for row in second.players]


def test_dgw_eligibility_is_shared_once_and_second_fixture_is_not_recaptured(model):
    native, roster, calendar = native_case(dgw=True, probabilities={(63, 6): 0.8, (69, 6): 0.6})
    before = _adjusted(native, model)
    adjusted = _adjusted(native, model, changed=True)
    pd.testing.assert_frame_equal(
        adjusted.loc[adjusted.fixture.eq(69), native.columns.difference(["model_version"])],
        before.loc[before.fixture.eq(69), native.columns.difference(["model_version"])],
        check_exact=True,
    )
    weekly = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=6, eligibility=_eligibility(**{"6": 0.75})
    )
    row = weekly.set_index("player_id").loc[6]
    points = adjusted.loc[adjusted.player_code.eq(6), "expected_points"]
    assert row.expected_points == pytest.approx(0.75 * points.sum())
    assert row.appearance_probability == pytest.approx(0.69)
    assert row.appearance_probability != pytest.approx(1 - (1 - 0.75 * 0.8) * (1 - 0.75 * 0.6))
    assert row.fixture_count == 2


def test_unavailable_teammate_is_zero_without_redistributing_to_other_players(model):
    native, roster, calendar = native_case()
    adjusted = _adjusted(native, model, changed=True)
    first = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=6, eligibility=_eligibility()
    )
    second = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=6, eligibility=_eligibility(**{"12": 0.0})
    )
    before, after = first.set_index("player_id"), second.set_index("player_id")
    assert after.at[12, "expected_points"] == after.at[12, "appearance_probability"] == 0
    pd.testing.assert_frame_equal(before.drop(index=12), after.drop(index=12), check_exact=True)


def test_zero_mass_keeps_declared_share_semantics_without_imputing_events(model):
    native, roster, calendar = native_case(zero_mass=True)
    adjusted = _adjusted(native, model, changed=True)
    assert adjusted.goals.eq(0).all() and adjusted.assists.eq(0).all()
    for _, side in adjusted.groupby(["fixture", "club"]):
        assert side.goals_share.sum() == pytest.approx(1.0)
        assert side.assists_share.sum() == pytest.approx(1.0)
    weekly = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=6, eligibility=_eligibility()
    )
    assert weekly.expected_points.notna().all()


def test_negative_native_points_are_recomputed_then_clipped_per_fixture(model):
    native, roster, calendar = native_case(negative_player=6)
    adjusted = _adjusted(native, model, changed=True)
    source = native.loc[native.player_code.eq(6)].iloc[0]
    result = adjusted.loc[adjusted.player_code.eq(6)].iloc[0]
    assert source.raw_expected_points < 0 and source.expected_points == 0
    expected_raw = _native_points(result)
    assert result.raw_expected_points == pytest.approx(expected_raw)
    assert result.expected_points == max(expected_raw, 0)
    delta_only = (
        source.expected_points
        + 6 * (result.goals - source.goals)
        + 3 * (result.assists - source.assists)
    )
    assert result.expected_points != pytest.approx(max(delta_only, 0))
    weekly = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=6, eligibility=_eligibility()
    )
    assert weekly.set_index("player_id").at[6, "expected_points"] == result.expected_points


def test_valid_blank_gameweek_is_distinguished_from_missing_fixture_rows(model):
    native, roster, calendar = native_case(bgw=True)
    adjusted = _adjusted(native, model, changed=True)
    blank = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=7, eligibility=_eligibility()
    )
    missing_club_match = blank.club_code.isin((1, 2, 3, 4))
    assert blank.loc[missing_club_match, "expected_points"].eq(0).all()
    assert blank.loc[missing_club_match, "appearance_probability"].eq(0).all()
    assert blank.loc[missing_club_match, "fixture_count"].eq(0).all()
    assert blank.loc[~missing_club_match, "fixture_count"].eq(1).all()
    with pytest.raises(ValueError):
        phase_weekly_forecast(roster, adjusted, calendar, gameweek=8, eligibility=_eligibility())
    missing = adjusted.loc[~(adjusted.fixture.eq(63) & adjusted.player_code.eq(6))].copy()
    with pytest.raises(ValueError):
        phase_weekly_forecast(roster, missing, calendar, gameweek=6, eligibility=_eligibility())


def test_native_absence_prevents_a_ranked_recipient_from_receiving_attacking_counts(model):
    native, roster, calendar = native_case(probabilities={(63, 6): 0.0})
    adjusted = _adjusted(native, model, changed=True)
    absent = adjusted.loc[adjusted.player_code.eq(6)].iloc[0]
    assert absent.goals == absent.assists == 0
    assert absent.goals_share == absent.assists_share == 0
    assert absent.appearance_probability == absent.expected_minutes == 0
    weekly = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=6, eligibility=_eligibility(**{"6": 0.75})
    )
    assert weekly.set_index("player_id").at[6, "appearance_probability"] == 0
    assert weekly.set_index("player_id").at[6, "expected_points"] == 0


def test_projected_decision_cannot_replace_an_explicit_earlier_native_cutoff(model):
    native, _, _ = native_case()
    projections = []
    for fixture, club in native.groupby(["fixture", "club"]).groups:
        document = projection_document(native, fixture=int(fixture), club=int(club))
        document["decision_at"] = "2026-09-22T13:00:00Z"
        projections.append(read_projection(document))
    with pytest.raises(ValueError, match=r"decision|cutoff"):
        phase_fixture_components(native, tuple(projections), model, season="2026-27")


def test_state_mass_times_recipient_share_is_integrated_before_averaging(model):
    native, _, _ = native_case(probabilities={(63, 6): 0.5})
    document = projection_document(native)
    first, second = document["states"]
    first.update(goal_mass=1.0, assist_mass=0.3, physical_goal_mass=1.0)
    second.update(goal_mass=5.0, assist_mass=1.5, physical_goal_mass=5.0)
    mixture = read_projection(document, penalty=12, delivery=6)
    projections = tuple(
        mixture if item.fixture == 63 and item.club == 6 else item for item in _projections(native)
    )
    adjusted = phase_fixture_components(native, projections, model, season="2026-27")
    single_state_predictions = []
    for state in document["states"]:
        single = {**document, "states": [{**state, "weight": 1.0}]}
        prediction = model.predict(read_projection(single, penalty=12, delivery=6))
        single_state_predictions.append((state["weight"], prediction))
    actual = adjusted.loc[adjusted.player_code.eq(6)].iloc[0]
    expected = math.fsum(
        weight * next(player.assists for player in allocation.players if player.player_code == 6)
        for weight, allocation in single_state_predictions
    )
    averaged_share = math.fsum(
        weight
        * next(player.assists_share for player in allocation.players if player.player_code == 6)
        for weight, allocation in single_state_predictions
    )
    assert actual.assists == pytest.approx(expected, abs=1e-12)
    assert actual.assists != pytest.approx(0.9 * averaged_share, abs=1e-4)
    assert adjusted.loc[adjusted.club.eq(6), "goals"].sum() == pytest.approx(3.0)
    assert adjusted.loc[adjusted.club.eq(6), "assists"].sum() == pytest.approx(0.9)


@pytest.mark.parametrize("marker", ["column", "attrs"])
def test_explicit_already_applied_availability_is_refused(model, marker):
    native, _, _ = native_case()
    if marker == "column":
        native["availability_multiplier"] = 0.75
    else:
        native.attrs["availability_application"] = "applied"
    with pytest.raises(ValueError, match=r"eligib|availability|native"):
        _adjusted(native, model, changed=True)


def test_component_attrs_are_preserved_and_bound_to_private_weekly_receipt(model):
    native, roster, calendar = native_case()
    adjusted = _adjusted(native, model, changed=True)
    for key, value in native.attrs.items():
        assert adjusted.attrs[key] == value
    adjusted.attrs["native_reference"] = "different source"
    with pytest.raises(ValueError):
        phase_weekly_forecast(roster, adjusted, calendar, gameweek=6, eligibility=_eligibility())


@pytest.mark.parametrize("field", ["bank_tenths", "free_transfers", "chip", "transfer_policy"])
def test_resource_attrs_are_bound_before_fixed_fifteen_role_search(model, field):
    native, roster, calendar = native_case()
    adjusted = _adjusted(native, model, changed=True)
    weekly = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=6, eligibility=_eligibility()
    )
    weekly.attrs[field] = "changed"
    with pytest.raises(ValueError):
        phase_fixed_fifteen_decision(weekly, XI, BENCH, 13, 8)


def test_nested_native_resource_policy_is_deeply_preserved(model):
    native, roster, calendar = native_case()
    adjusted = _adjusted(native, model, changed=True)
    weekly = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=6, eligibility=_eligibility()
    )
    roster.attrs["transfer_policy"]["inventory"] = "different"
    assert weekly.attrs["transfer_policy"]["inventory"] == "fixed"


@pytest.mark.parametrize("damage", ["club_collision", "team_collision", "boolean_team"])
def test_native_persistent_club_and_season_team_mapping_must_be_one_to_one(model, damage):
    native, roster, calendar = native_case()
    adjusted = _adjusted(native, model, changed=True)
    if damage == "club_collision":
        roster.loc[roster.player_id.eq(6), "team_id"] = 103
    elif damage == "team_collision":
        roster.loc[roster.club_code.eq(6), "team_id"] = 103
    else:
        roster = roster.astype({"team_id": object})
        roster.loc[roster.player_id.eq(6), "team_id"] = True
    with pytest.raises(ValueError):
        phase_weekly_forecast(roster, adjusted, calendar, gameweek=6, eligibility=_eligibility())


@pytest.mark.parametrize(
    "column", ["goals", "assists", "expected_points", "appearance_probability"]
)
def test_private_component_receipts_bind_actual_values_after_the_adapter(model, column):
    native, roster, calendar = native_case()
    adjusted = _adjusted(native, model, changed=True)
    damaged = adjusted.copy(deep=True)
    damaged.loc[damaged.player_code.eq(6), column] += 0.01
    with pytest.raises(ValueError):
        phase_weekly_forecast(roster, damaged, calendar, gameweek=6, eligibility=_eligibility())


def test_private_weekly_receipts_bind_values_before_role_search(model):
    native, roster, calendar = native_case()
    adjusted = _adjusted(native, model, changed=True)
    weekly = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=6, eligibility=_eligibility()
    )
    damaged = weekly.copy(deep=True)
    damaged.loc[damaged.player_id.eq(12), "expected_points"] += 1
    with pytest.raises(ValueError):
        phase_fixed_fifteen_decision(damaged, XI, BENCH, 13, 8)


@pytest.mark.parametrize("damage", ["mass", "minutes", "baseline", "player", "fixture"])
def test_complete_projection_must_match_its_claimed_native_basis(model, damage):
    native, _, _ = native_case()
    document = projection_document(native)
    if damage == "mass":
        document["states"][0]["goal_mass"] *= 0.5
    elif damage == "minutes":
        document["states"][0]["players"][0]["minutes"] = 75.0
    elif damage == "baseline":
        document["states"][0]["players"][0]["goal_weight90"] = 2.0
    elif damage == "player":
        document["states"][0]["players"][0]["player_code"] = 999
    else:
        document["fixture"] = 999
    with pytest.raises(ValueError):
        projection = read_projection(document)
        phase_fixture_components(native, (projection,), model, season="2026-27")


def test_disabled_candidate_preserves_native_frame_exactly(model):
    native, _, _ = native_case()
    actual = _adjusted(native, model, changed=True, enabled=False)
    pd.testing.assert_frame_equal(actual, native, check_exact=True)


@pytest.mark.parametrize("chip", [None, "3xc", "bboost", "wildcard", "freehit"])
def test_chip_and_hit_expectations_agree_with_independent_official_rules(model, chip):
    native, roster, calendar = native_case()
    adjusted = _adjusted(native, model, changed=True)
    weekly = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=6, eligibility=_eligibility(**{"6": 0.75, "13": 0.75})
    )
    result = phase_fixed_fifteen_decision(weekly, XI, BENCH, 13, 8, chip=chip, hit_points=4)
    assert result.best.expected_net_points == pytest.approx(
        _official_expectation(weekly, result.best, chip=chip, hit_points=4), abs=1e-11
    )


def test_locked_action_and_small_budget_preserve_full_action_and_fifteen(model):
    native, roster, calendar = native_case()
    adjusted = _adjusted(native, model, changed=True)
    weekly = phase_weekly_forecast(
        roster, adjusted, calendar, gameweek=6, eligibility=_eligibility()
    )
    locked = phase_fixed_fifteen_decision(weekly, XI, BENCH, 13, 8, locked_first=True)
    bounded = phase_fixed_fifteen_decision(weekly, XI, BENCH, 13, 8, max_evaluations=1)
    assert locked.best == locked.incumbent
    assert bounded.best == bounded.incumbent
    assert locked.best.starting_xi == XI
    assert locked.best.ordered_bench == BENCH
    assert (locked.best.captain_id, locked.best.vice_captain_id) == (13, 8)
    assert bounded.evaluations == 1
    assert set(bounded.best.starting_xi) | set(bounded.best.ordered_bench) == set(range(1, 16))
