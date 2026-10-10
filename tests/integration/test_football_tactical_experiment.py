"""Raw synthetic tactical sources through learning, native replacement and legal roles."""

from __future__ import annotations

import json
import math
from collections import Counter
from dataclasses import replace
from itertools import product
from typing import Any

import numpy as np
import pandas as pd
import pytest
from tests.football_tactical_fixtures import (
    BENCH,
    CAPTURED,
    CUTOFF,
    DEADLINE,
    GAMEWEEK,
    RESOURCES,
    SEASON,
    XI,
    TacticalWorld,
    fitted,
    observations,
    projection_document,
    read_projection,
    world,
)

import squadopt.application.football_tactical_experiment as experiment
from squadopt.application.football_tactical_experiment import (
    compose_tactical_candidate,
    plan_tactical_fixed_fifteen,
)
from squadopt.features.football_tactical_inputs import (
    STYLE_COUNTS,
    TRAITS,
    TacticalPlayerState,
    TacticalProjection,
)
from squadopt.live.minute_evidence import _score_components
from squadopt.prediction.football_components import COMPONENT_COLUMNS
from squadopt.prediction.football_tactical_matchup import TacticalMatchupModel


@pytest.fixture(scope="module")
def model() -> TacticalMatchupModel:
    return fitted()


def compose(w: TacticalWorld, model: TacticalMatchupModel | None, **changes: Any) -> Any:
    arguments = dict(
        model=model,
        projections=w.projections,
        roster=w.roster,
        fixture_calendar=w.calendar,
        season=SEASON,
        gameweeks=tuple(sorted(set(w.calendar.GW))),
        captured_at=CAPTURED,
        native_cutoff=CUTOFF,
        deadline_at=DEADLINE,
        captured_availability=w.availability,
        resource_bundle=RESOURCES,
    )
    arguments.update(changes)
    return compose_tactical_candidate(w.native, **arguments)


def fixed(w: TacticalWorld, candidate: Any, **changes: Any) -> Any:
    arguments = dict(
        squad=w.roster.loc[w.roster.player_id.le(15)].copy(deep=True),
        gameweek=GAMEWEEK,
        starting_xi=XI,
        ordered_bench=BENCH,
        captain_id=13,
        vice_captain_id=14,
        resource_bundle=RESOURCES,
    )
    arguments.update(changes)
    return plan_tactical_fixed_fifteen(candidate, **arguments)


def _named_feature(
    name: str,
    p: TacticalProjection,
    state: Any,
    home: bool,
    player: TacticalPlayerState | None = None,
) -> float:
    """Interpret the public named vocabulary without production feature/scoring helpers."""
    if player is not None and player.minutes == 0:
        return 0.0
    if "*" in name:
        return math.prod(_named_feature(part, p, state, home, player) for part in name.split("*"))
    own, opponent = (state.home, state.away) if home else (state.away, state.home)
    own_style, other_style = (p.home_style, p.away_style) if home else (p.away_style, p.home_style)
    for prefix, style in (("own_style_", own_style), ("opponent_style_", other_style)):
        if name.startswith(prefix):
            return (
                90
                * float(style.counts[STYLE_COUNTS.index(name.removeprefix(prefix))])
                / math.fsum(f.minutes for f in style.fixtures)
            )
    if name.startswith("player_"):
        assert player is not None
        return float(player.profile.attributes[TRAITS.index(name.removeprefix("player_"))]) / 20
    if name.startswith("role_"):
        assert player is not None
        return float(player.tactical_role == name.removeprefix("role_"))
    if name.startswith("own_goal_weighted_"):
        players, trait = (
            [(x, x.native_goal_share) for x in own.players],
            name.removeprefix("own_goal_weighted_"),
        )
    elif name.startswith("own_assist_weighted_"):
        players, trait = (
            [(x, x.native_assist_share) for x in own.players],
            name.removeprefix("own_assist_weighted_"),
        )
    elif name.startswith("opponent_defending_"):
        players, trait = (
            [
                (x, x.minutes)
                for x in opponent.players
                if x.tactical_role in ("defender", "midfielder")
            ],
            name.removeprefix("opponent_defending_"),
        )
    else:
        assert name == "opponent_gk_aerial_reach"
        players, trait = (
            [(x, x.minutes) for x in opponent.players if x.tactical_role == "goalkeeper"],
            "gk_aerial_reach",
        )
    return math.fsum(
        weight * float(x.profile.attributes[TRAITS.index(trait)]) / 20
        for x, weight in players
        if weight
    ) / math.fsum(weight for _, weight in players)


def state_oracle(
    p: TacticalProjection, model: TacticalMatchupModel, *, control: bool = False
) -> dict[int, dict[str, float]]:
    metadata = model.metadata
    values: dict[int, dict[str, float]] = {}
    for state in p.states:
        rates = []
        for home, own in ((True, state.home), (False, state.away)):
            log_ratio = (
                0
                if control
                else math.fsum(
                    coefficient * (_named_feature(name, p, state, home) - mean) / scale
                    for name, mean, scale, coefficient in zip(
                        metadata.team_transform.features,
                        metadata.team_transform.means,
                        metadata.team_transform.scales,
                        metadata.beta,
                        strict=True,
                    )
                )
            )
            rates.append(own.base_goal_rate * math.exp(log_ratio))
        for side_index, own in enumerate((state.home, state.away)):
            rate, opponent = rates[side_index], rates[1 - side_index]
            players = sorted(own.players, key=lambda x: x.profile.player_code)
            heads = {}
            for head, transform, coefficients, fraction in (
                ("goals", metadata.goal_transform, metadata.goal_gamma, own.scored_fraction),
                (
                    "assists",
                    metadata.assist_transform,
                    metadata.assist_gamma,
                    own.scored_fraction * own.assist_fraction,
                ),
            ):
                shares = [
                    getattr(x, "native_goal_share" if head == "goals" else "native_assist_share")
                    for x in players
                ]
                if control:
                    probabilities = shares
                else:
                    logs = [
                        math.log(share)
                        + math.fsum(
                            coefficient
                            * (_named_feature(name, p, state, side_index == 0, x) - mean)
                            / scale
                            for name, mean, scale, coefficient in zip(
                                transform.features,
                                transform.means,
                                transform.scales,
                                coefficients,
                                strict=True,
                            )
                        )
                        if share
                        else -math.inf
                        for x, share in zip(players, shares, strict=True)
                    ]
                    weights = [math.exp(log - max(logs)) for log in logs]
                    probabilities = [weight / math.fsum(weights) for weight in weights]
                heads[head] = [rate * fraction * probability for probability in probabilities]
            for index, player in enumerate(players):
                record = values.setdefault(
                    player.profile.player_code,
                    dict(
                        team_goal_rate=0.0,
                        opponent_goal_rate=0.0,
                        goals=0.0,
                        assists=0.0,
                        clean_sheet_probability=0.0,
                    ),
                )
                record["team_goal_rate"] += state.weight * rate
                record["opponent_goal_rate"] += state.weight * opponent
                record["goals"] += state.weight * heads["goals"][index]
                record["assists"] += state.weight * heads["assists"][index]
                record["clean_sheet_probability"] += state.weight * (
                    math.exp(-opponent * player.minutes / 90) if player.minutes >= 60 else 0
                )
    return values


def official_points(squad: pd.DataFrame, score: Any) -> float:
    """Enumerate actual played masks, sequential legal autosubs and captain fallback."""
    rows = squad.set_index("player_id")
    ids = tuple(rows.index)
    uncertain = [code for code in ids if 0 < rows.loc[code, "appearance_probability"] < 1]
    always = {code for code in ids if rows.loc[code, "appearance_probability"] == 1}
    total = 0.0
    for bits in product((False, True), repeat=len(uncertain)):
        played = always | {code for code, bit in zip(uncertain, bits, strict=True) if bit}
        weight = math.prod(
            float(rows.loc[code, "appearance_probability"])
            if bit
            else 1 - float(rows.loc[code, "appearance_probability"])
            for code, bit in zip(uncertain, bits, strict=True)
        )
        starters = set(score.starting_xi)
        selected = starters & played
        if score.chip == "bboost":
            selected = played
        else:
            keeper = score.ordered_bench[0]
            if keeper in played and not any(rows.loc[x, "position"] == "GK" for x in selected):
                selected.add(keeper)
            absent = Counter(
                str(rows.loc[x, "position"])
                for x in starters - played
                if rows.loc[x, "position"] != "GK"
            )
            formation = Counter(
                str(rows.loc[x, "position"]) for x in starters if rows.loc[x, "position"] != "GK"
            )
            for reserve in score.ordered_bench[1:]:
                if reserve not in played:
                    continue
                position = str(rows.loc[reserve, "position"])
                options = [position, *[p for p in ("DEF", "MID", "FWD") if p != position]]
                for missing in options:
                    hypothetical = formation.copy()
                    hypothetical[missing] -= 1
                    hypothetical[position] += 1
                    if (
                        absent[missing]
                        and 3 <= hypothetical["DEF"] <= 5
                        and 2 <= hypothetical["MID"] <= 5
                        and 1 <= hypothetical["FWD"] <= 3
                    ):
                        absent[missing] -= 1
                        formation = hypothetical
                        selected.add(reserve)
                        break
        points = math.fsum(
            float(rows.loc[x, "expected_points"]) / float(rows.loc[x, "appearance_probability"])
            for x in selected
        )
        captain = score.captain_id if score.captain_id in played else score.vice_captain_id
        if captain in played:
            points += (
                (2 if score.chip == "3xc" else 1)
                * float(rows.loc[captain, "expected_points"])
                / float(rows.loc[captain, "appearance_probability"])
            )
        total += weight * (points - score.hit_points)
    return total


def test_raw_source_fit_controls_native_and_learned_components_against_independent_oracle(
    model: TacticalMatchupModel,
) -> None:
    w = world()
    before_native, before_roster = w.native.copy(deep=True), w.roster.copy(deep=True)
    control, candidate = compose(w, model, control=True), compose(w, model)
    assert len(model.metadata.training_receipts) == 12
    assert model.metadata.goal_events == 54 and model.metadata.assist_events == 18
    assert all(receipt.projection_source.raw_sha256 for receipt in model.metadata.training_receipts)
    pd.testing.assert_frame_equal(
        control.components[list(COMPONENT_COLUMNS)], w.native[list(COMPONENT_COLUMNS)]
    )
    for p in w.projections:
        expected = state_oracle(p, model)
        actual = candidate.components.loc[candidate.components.fixture.eq(p.fixture)].set_index(
            "player_code"
        )
        native = w.native.loc[w.native.fixture.eq(p.fixture)].set_index("player_code")
        for code, components in expected.items():
            for key, number in components.items():
                assert actual.loc[code, key] == pytest.approx(number, rel=1e-10, abs=1e-10)
            row = actual.loc[code]
            goal_coefficient = {"GK": 10, "DEF": 6, "MID": 5, "FWD": 4}[row.position]
            clean_coefficient = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}[row.position]
            raw = (
                row.appearance_probability
                + row.p60
                + goal_coefficient * components["goals"]
                + 3 * components["assists"]
                + clean_coefficient * components["clean_sheet_probability"]
                + 2 * row.defcon_probability
                + row.appearance_probability * row.residual_if_appearance
            )
            assert row.raw_expected_points == pytest.approx(raw)
            assert row.expected_points == max(row.raw_expected_points, 0)
            for key in (
                "expected_minutes",
                "appearance_probability",
                "p60",
                "defcon_probability",
                "residual_if_appearance",
                *(f"minute_probability_{i}" for i in range(4)),
                *(f"minute_value_{i}" for i in range(4)),
            ):
                assert row[key] == native.loc[code, key]
        for _club, rows in actual.groupby("club"):
            rate = float(rows.team_goal_rate.iloc[0])
            assert rows.goals.sum() == pytest.approx(0.8 * rate)
            assert rows.assists.sum() == pytest.approx(0.8 * 0.6 * rate)
            assert rows.goals_share.sum() == pytest.approx(1)
            assert rows.assists_share.sum() == pytest.approx(1)
    pd.testing.assert_frame_equal(w.native, before_native)
    pd.testing.assert_frame_equal(w.roster, before_roster)
    assert json.loads(candidate.resource_bundle_json) == RESOURCES


def test_joint_state_clean_sheets_are_not_exponentials_of_mean_rates(
    model: TacticalMatchupModel,
) -> None:
    w = world()
    candidate = compose(w, model)
    row = candidate.components.loc[candidate.components.player_code.eq(5)].iloc[0]
    predicted = model.predict(w.projections[2])
    assert len({state.away_goal_rate for state in predicted.states}) == 2
    expected = math.fsum(
        state.weight * math.exp(-state.away_goal_rate * minutes / 90)
        for state, minutes in zip(predicted.states, (75, 90), strict=True)
    )
    assert row.clean_sheet_probability == pytest.approx(expected, rel=1e-12, abs=1e-13)
    assert not math.isclose(
        row.clean_sheet_probability,
        math.exp(-row.opponent_goal_rate),
        rel_tol=1e-8,
        abs_tol=1e-12,
    )
    intermittent = candidate.components.loc[candidate.components.player_code.eq(6)].iloc[0]
    expected_active = next(s for s in predicted.states if s.state_id == "present")
    assert intermittent.clean_sheet_probability == pytest.approx(
        0.8 * math.exp(-expected_active.home_goal_rate), rel=1e-12, abs=1e-13
    )
    assert (
        abs(
            intermittent.clean_sheet_probability
            - intermittent.p60 * math.exp(-intermittent.opponent_goal_rate)
        )
        > 1e-4
    )


def test_learned_matchup_reaches_legal_starting_captain_and_ordered_reserve_roles(
    model: TacticalMatchupModel,
) -> None:
    w = world()
    control = fixed(w, compose(w, model, control=True))
    learned = fixed(w, compose(w, model))
    assert 12 not in control.search.best.starting_xi
    assert 12 in learned.search.best.starting_xi
    assert learned.search.best.captain_id == 12
    assert learned.search.best.expected_net_points > learned.search.incumbent.expected_net_points
    assert learned.search.proof_scope == "bounded_fixed_squad_neighborhood_only"
    assert learned.search.evaluations <= 128
    assert set(learned.search.best.starting_xi) | set(learned.search.best.ordered_bench) == set(
        range(1, 16)
    )
    assert learned.search.best.ordered_bench[0] == 2
    assert learned.search.best.ordered_bench[1:] == (6, 7, 11)
    worse_order = replace(learned.search.best, ordered_bench=(2, 7, 6, 11))
    assert official_points(learned.squad, learned.search.best) > official_points(
        learned.squad, worse_order
    )
    assert learned.search.best.expected_net_points == pytest.approx(
        official_points(learned.squad, learned.search.best)
    )
    assert learned.search.incumbent.expected_net_points == pytest.approx(
        official_points(learned.squad, learned.search.incumbent)
    )
    assert json.loads(learned.resource_bundle_json) == RESOURCES


def test_opponent_named_defense_changes_the_forecast_without_manual_weights(
    model: TacticalMatchupModel,
) -> None:
    weak, strong = world(defense=3), world(defense=18)
    weak_candidate, strong_candidate = compose(weak, model), compose(strong, model)
    weak_points = weak_candidate.weekly.query(
        "player_id == 12 and gameweek == 6"
    ).expected_points.iloc[0]
    strong_points = strong_candidate.weekly.query(
        "player_id == 12 and gameweek == 6"
    ).expected_points.iloc[0]
    assert weak_points > strong_points + 10
    assert (
        fixed(weak, weak_candidate).search.best.captain_id
        != fixed(strong, strong_candidate).search.best.captain_id
    )


def test_double_gameweek_eligibility_is_shared_once_for_union_appearance(
    model: TacticalMatchupModel,
) -> None:
    w = world(double=True)
    candidate = compose(w, model)
    row = candidate.weekly.query("player_id == 6 and gameweek == 6").iloc[0]
    components = candidate.components.loc[candidate.components.player_code.eq(6)]
    assert len(components) == 2
    assert row.expected_points == pytest.approx(0.75 * components.expected_points.sum())
    assert row.appearance_probability == pytest.approx(0.75 * (1 - (1 - 0.8) ** 2))
    assert row.appearance_probability != pytest.approx(1 - (1 - 0.75 * 0.8) ** 2)


def test_captured_blank_week_is_distinct_from_an_omitted_calendar_week(
    model: TacticalMatchupModel,
) -> None:
    w = world(blank=True)
    candidate = compose(w, model)
    row = candidate.weekly.query("player_id == 6 and gameweek == 6").iloc[0]
    assert row.expected_points == 0 and row.appearance_probability == 0
    with pytest.raises(ValueError):
        compose(w, model, gameweeks=(6, 7, 8))


@pytest.mark.parametrize("chip", [None, "bboost", "3xc"])
def test_chips_hits_and_locked_roles_match_independent_official_score(
    model: TacticalMatchupModel, chip: str | None
) -> None:
    w = world()
    candidate = compose(w, model)
    plan = fixed(w, candidate, chip=chip, hit_points=4.0, locked_first=True)
    assert plan.search.best.starting_xi == XI
    assert plan.search.best.ordered_bench == BENCH
    assert plan.search.best.expected_net_points == pytest.approx(
        official_points(plan.squad, plan.search.best)
    )


def test_disabled_route_preserves_native_numbers_and_never_needs_tactical_input() -> None:
    w = world()
    candidate = compose(w, None, enabled=False, projections=())
    pd.testing.assert_frame_equal(candidate.components, w.native)
    for row in candidate.weekly.itertuples(index=False):
        native = w.native.loc[w.native.player_code.eq(row.player_id)]
        assert row.expected_points == pytest.approx(
            w.availability[row.player_id] * native.expected_points.sum()
        )


def test_clipping_happens_at_fixture_before_weekly_eligibility(model: TacticalMatchupModel) -> None:
    w = world(double=True, residual=-100.0)
    candidate = compose(w, model)
    assert candidate.components.raw_expected_points.lt(0).all()
    assert candidate.components.expected_points.eq(0).all()
    assert candidate.weekly.expected_points.eq(0).all()


@pytest.mark.parametrize("zero_fit", [False, True])
def test_zero_native_intensities_preserve_zero_attacking_channels(
    monkeypatch: pytest.MonkeyPatch, zero_fit: bool
) -> None:
    w = world(zero_rates=True)
    model = fitted(zero=zero_fit)
    if not zero_fit:
        assert any((*model.metadata.beta, *model.metadata.goal_gamma, *model.metadata.assist_gamma))
    original_replace = experiment._replace
    calls = []

    def record_replace(*arguments: Any, **keywords: Any) -> pd.DataFrame:
        revised = original_replace(*arguments, **keywords)
        calls.append(revised.copy(deep=True))
        return revised

    monkeypatch.setattr(experiment, "_replace", record_replace)
    candidate = compose(w, model)
    assert len(calls) == 1
    assert candidate.components.goals.eq(0).all()
    assert candidate.components.assists.eq(0).all()
    assert candidate.components.clean_sheet_probability.eq(candidate.components.p60).all()
    if not zero_fit:
        pd.testing.assert_frame_equal(candidate.components, calls[0])


@pytest.mark.parametrize(
    "damage",
    ["points", "goals", "minutes", "cutoff", "double-eligibility", "duplicate", "nonfinite"],
)
def test_native_control_and_identity_damage_refuse(
    model: TacticalMatchupModel, damage: str
) -> None:
    w = world()
    native = w.native.copy(deep=True)
    if damage == "points":
        native.loc[0, "expected_points"] += 1
    elif damage == "goals":
        native.loc[0, "goals"] += 0.1
        native = _score_components(native)
    elif damage == "minutes":
        native.loc[0, "minute_value_3"] = 100
        native = _score_components(native)
    elif damage == "cutoff":
        native["decision_at"] = "2026-10-09T00:01:00Z"
    elif damage == "double-eligibility":
        native["availability_multiplier"] = 0.75
    elif damage == "duplicate":
        native = pd.concat([native, native.iloc[:1]], ignore_index=True)
    else:
        native.loc[0, "goals"] = np.inf
    with pytest.raises(ValueError):
        compose(replace(w, native=native), model)


@pytest.mark.parametrize(
    "damage",
    [
        "missing-player",
        "missing-side",
        "duplicate-calendar",
        "missing-fixture",
        "wrong-opponent",
        "future-source",
        "missing-gk",
        "unknown-trait",
        "unknown-style",
        "ambiguous-uid",
    ],
)
def test_complete_source_coverage_named_channels_and_calendar_refuse(
    model: TacticalMatchupModel, damage: str
) -> None:
    w = world()
    if damage == "missing-player":
        w = replace(w, roster=w.roster.iloc[1:].copy())
    elif damage == "missing-side":
        w = replace(
            w, native=w.native.loc[~(w.native.fixture.eq(7201) & w.native.home.eq(1))].copy()
        )
    elif damage == "duplicate-calendar":
        w = replace(w, calendar=pd.concat([w.calendar, w.calendar.iloc[:1]], ignore_index=True))
    elif damage == "missing-fixture":
        w = replace(w, projections=w.projections[:-1])
    elif damage == "wrong-opponent":
        calendar = w.calendar.copy()
        calendar.loc[0, "opponent"] = 6
        w = replace(w, calendar=calendar)
    else:
        p = w.projections[2]
        document = projection_document(p)
        if damage == "future-source":
            document["states"][0]["home"]["players"][0]["profile"]["source"]["published_at"] = (
                "2026-10-09T00:01:00Z"
            )
        elif damage == "missing-gk":
            for state in document["states"]:
                for player in state["home"]["players"]:
                    if player["tactical_role"] == "goalkeeper":
                        player["tactical_role"] = "defender"
        elif damage == "unknown-trait":
            for state in document["states"]:
                for player in state["home"]["players"]:
                    if player["tactical_role"] == "goalkeeper":
                        player["profile"]["attributes"]["gk_aerial_reach"] = None
        elif damage == "unknown-style":
            document["home_style"]["counts"]["cross_attempts"] = None
        else:
            for state in document["states"]:
                state["home"]["players"][1]["profile"]["original_identity"] = state["home"][
                    "players"
                ][0]["profile"]["original_identity"]
        with pytest.raises(ValueError):
            altered = read_projection(p, document)
            compose(replace(w, projections=(*w.projections[:2], altered)), model)
        return
    with pytest.raises(ValueError):
        compose(w, model)


@pytest.mark.parametrize(
    "field", ["buy_price_tenths", "sell_price_tenths", "club_code", "position", "name"]
)
def test_fixed_fifteen_cannot_change_captured_resources_or_identity(
    model: TacticalMatchupModel, field: str
) -> None:
    w = world()
    candidate = compose(w, model)
    squad = w.roster.loc[w.roster.player_id.le(15)].copy()
    squad.loc[squad.player_id.eq(1), field] = (
        "different" if field == "name" else "MID" if field == "position" else 999
    )
    with pytest.raises(ValueError):
        fixed(w, candidate, squad=squad)


def test_target_gameweek_and_protected_training_refuse_before_forecast_fit() -> None:
    original = observations()[0]
    with pytest.raises(ValueError, match="target"):
        TacticalMatchupModel().fit(
            (original,),
            cutoff=CUTOFF,
            allowed_seasons=("2024-25",),
            target_season="2024-25",
            target_gameweek=original.projection.gameweek,
        )
    with pytest.raises(ValueError, match=r"protected|admitted"):
        TacticalMatchupModel().fit(
            (original,),
            cutoff=CUTOFF,
            allowed_seasons=("2024-25", "2025-26"),
            target_season=SEASON,
            target_gameweek=GAMEWEEK,
        )


def test_named_optional_resources_and_source_attrs_are_preserved(
    model: TacticalMatchupModel,
) -> None:
    w = world()
    roster = w.roster.copy(deep=True)
    roster["purchase_capture_id"] = [f"synthetic-purchase-{code}" for code in roster.player_id]
    roster["squad_status"] = "retained"
    roster.attrs["private_inventory"] = {"capture": "synthetic-inventory-1", "bank_tenths": 17}
    w = replace(w, roster=roster)
    candidate = compose(w, model)
    plan = fixed(w, candidate)
    for frame in (candidate.roster, candidate.weekly, plan.squad):
        assert frame.attrs["private_inventory"] == roster.attrs["private_inventory"]
        actual = frame.set_index("player_id")
        for code in actual.index:
            for key in ("purchase_capture_id", "squad_status"):
                assert actual.loc[code, key] == roster.set_index("player_id").loc[code, key]
    original = roster.loc[roster.player_id.le(15)].copy()
    with pytest.raises(ValueError):
        altered = original.copy(deep=True)
        altered.loc[altered.player_id.eq(1), "purchase_capture_id"] = "changed-capture"
        fixed(w, candidate, squad=altered)
    with pytest.raises(ValueError):
        altered = original.copy(deep=True)
        altered.attrs["private_inventory"]["bank_tenths"] = 999
        fixed(w, candidate, squad=altered)


@pytest.mark.parametrize("target", ["components", "weekly", "roster"])
@pytest.mark.parametrize("location", ["column", "attrs", "receipt"])
def test_bound_candidate_rejects_frame_and_attribute_tampering(
    model: TacticalMatchupModel, target: str, location: str
) -> None:
    w = world()
    candidate = compose(w, model)
    changed = getattr(candidate, target).copy(deep=True)
    if location == "column":
        key = "expected_points" if target != "roster" else "sell_price_tenths"
        changed.loc[changed.index[0], key] += 1
    elif location == "attrs":
        changed.attrs["resources"]["bank_tenths"] += 1
    else:
        changed.attrs["football_tactical_experiment_receipt"] = "{}"
    with pytest.raises(ValueError):
        fixed(w, replace(candidate, **{target: changed}))


def test_bound_resource_bundle_and_double_application_refuse(model: TacticalMatchupModel) -> None:
    w = world()
    candidate = compose(w, model)
    changed_resources = {**RESOURCES, "free_transfers": 3}
    with pytest.raises(ValueError):
        fixed(w, candidate, resource_bundle=changed_resources)
    with pytest.raises(ValueError):
        compose(replace(w, native=candidate.components), model)
    already_applied = w.native.copy(deep=True)
    already_applied.attrs["availability_application"] = "applied"
    with pytest.raises(ValueError):
        compose(replace(w, native=already_applied), model)


@pytest.mark.parametrize("damage", ["missing", "extra", "bool", "nonfinite", "outside"])
def test_captured_eligibility_must_be_exact_complete_and_finite(
    model: TacticalMatchupModel, damage: str
) -> None:
    w = world()
    values: Any = dict(w.availability)
    if damage == "missing":
        values.pop(6)
    elif damage == "extra":
        values[99999] = 1.0
    else:
        values[6] = {"bool": True, "nonfinite": float("nan"), "outside": 1.01}[damage]
    with pytest.raises(ValueError):
        compose(w, model, captured_availability=values)


def test_role_restrictions_resource_cap_and_keeper_fallback_reach_the_same_engine(
    model: TacticalMatchupModel,
) -> None:
    w = world()
    values = dict(w.availability)
    values[1] = 0.5
    w = replace(w, availability=values)
    candidate = compose(w, model)
    plan = fixed(w, candidate, not_starting=(12,), not_captain=(12,))
    assert 12 not in plan.search.best.starting_xi
    assert 12 not in (plan.search.best.captain_id, plan.search.best.vice_captain_id)
    assert plan.search.best.expected_net_points == pytest.approx(
        official_points(plan.squad, plan.search.best)
    )
    assert plan.search.incumbent.scoring_multipliers[2] == 0.5
    with pytest.raises(ValueError):
        fixed(w, candidate, max_evaluations=129)


def test_raw_joint_state_and_player_order_do_not_change_fixture_or_role_values(
    model: TacticalMatchupModel,
) -> None:
    w = world()
    reversed_projections = tuple(
        read_projection(
            replace(
                p,
                states=tuple(
                    replace(
                        state,
                        home=replace(state.home, players=tuple(reversed(state.home.players))),
                        away=replace(state.away, players=tuple(reversed(state.away.players))),
                    )
                    for state in reversed(p.states)
                ),
            )
        )
        for p in reversed(w.projections)
    )
    original = compose(w, model)
    reordered = compose(replace(w, projections=reversed_projections), model)
    pd.testing.assert_frame_equal(
        reordered.components,
        original.components,
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
        check_flags=False,
    )
    assert fixed(w, reordered).search.best.fingerprint == fixed(w, original).search.best.fingerprint


def test_opposing_sides_are_joined_by_identity_after_raw_home_away_reversal(
    model: TacticalMatchupModel,
) -> None:
    w = world()
    reversed_projections = tuple(
        read_projection(
            replace(
                p,
                home_club=p.away_club,
                away_club=p.home_club,
                home_style=p.away_style,
                away_style=p.home_style,
                states=tuple(replace(s, home=s.away, away=s.home) for s in p.states),
            )
        )
        for p in w.projections
    )
    native, calendar = w.native.copy(deep=True), w.calendar.copy(deep=True)
    native["home"] = 1 - native.home
    calendar["home"] = 1 - calendar.home
    reversed_world = replace(w, native=native, calendar=calendar, projections=reversed_projections)
    actual, original = compose(reversed_world, model), compose(w, model)
    pd.testing.assert_frame_equal(
        actual.components.drop(columns="home"),
        original.components.drop(columns="home"),
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )


@pytest.mark.parametrize("head", ["goals", "assists"])
def test_algebraically_valid_native_attacking_counts_still_bind_the_projection_control(
    model: TacticalMatchupModel, head: str
) -> None:
    w = world()
    native = w.native.copy(deep=True)
    side = native.loc[native.fixture.eq(7201) & native.club.eq(1)]
    donors = side.loc[side[head].gt(0)].index
    first, second = donors[:2]
    native.loc[first, head] += 0.05
    native.loc[second, head] -= 0.05
    native.loc[side.index, head + "_share"] = (
        native.loc[side.index, head] / native.loc[side.index, head].sum()
    )
    native = _score_components(native)
    assert native.loc[side.index, head].sum() == pytest.approx(side[head].sum())
    assert native.loc[side.index, head + "_share"].sum() == pytest.approx(1)
    with pytest.raises(ValueError, match="control"):
        compose(replace(w, native=native), model)


def test_split_identical_raw_joint_states_preserves_the_fixture_week_and_roles(
    model: TacticalMatchupModel,
) -> None:
    w = world()
    split_projections = tuple(
        read_projection(
            replace(
                p,
                states=tuple(
                    replace(state, state_id=f"{state.state_id}-{part}", weight=state.weight / 2)
                    for state in p.states
                    for part in (1, 2)
                ),
            )
        )
        for p in w.projections
    )
    original = compose(w, model)
    split = compose(replace(w, projections=split_projections), model)
    pd.testing.assert_frame_equal(
        split.components,
        original.components,
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )
    pd.testing.assert_frame_equal(
        split.weekly,
        original.weekly,
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )
    actual, expected = fixed(w, split).search.best, fixed(w, original).search.best
    for name in ("starting_xi", "ordered_bench", "captain_id", "vice_captain_id"):
        assert getattr(actual, name) == getattr(expected, name)
    assert actual.expected_net_points == pytest.approx(
        expected.expected_net_points, rel=1e-12, abs=1e-12
    )


def test_declared_near_unit_mass_is_normalized_in_native_minute_and_scoring_binding(
    model: TacticalMatchupModel,
) -> None:
    w = world()
    rounded = tuple(
        read_projection(
            replace(
                p,
                states=tuple(replace(s, weight=s.weight * (1 + 5e-13)) for s in p.states),
            )
        )
        for p in w.projections
    )
    assert all(math.fsum(s.weight for s in p.states) > 1 for p in rounded)
    actual, original = compose(replace(w, projections=rounded), model), compose(w, model)
    pd.testing.assert_frame_equal(
        actual.components,
        original.components,
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )
    pd.testing.assert_frame_equal(
        actual.weekly,
        original.weekly,
        check_exact=False,
        rtol=1e-12,
        atol=1e-12,
    )
    for p in rounded:
        predicted = model.predict(p)
        assert math.fsum(s.weight for s in predicted.states) == 1
