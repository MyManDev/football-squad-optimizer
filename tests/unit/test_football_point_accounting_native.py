"""Independent invented capture and accepted-native point-accounting witnesses."""

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from squadopt.contracts.football_point_accounting import (
    ComponentMoments,
    PointCoefficients,
    clip_points,
    raw_points,
)
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD
from squadopt.live.minute_evidence import _score_components
from squadopt.live.rules import ScoringRules, read_season_rules

POSITIONS = ("GK", "DEF", "MID", "FWD")


def _capture_rules(tmp_path: Path, *, custom: bool = False) -> ScoringRules:
    """Invented source bytes, never a historical or live capture admission."""
    scoring = {
        "long_play": 5 if custom else 2,
        "short_play": 3 if custom else 1,
        "assists": 7 if custom else 3,
        "saves": 1,
        "penalties_saved": 5,
        "penalties_missed": -2,
        "yellow_cards": -1,
        "red_cards": -3,
        "own_goals": -2,
        "bonus": 1,
        "goals_scored": dict(zip(("GKP", "DEF", "MID", "FWD"), (23, 19, 17, 13), strict=True)),
        "clean_sheets": dict(zip(("GKP", "DEF", "MID", "FWD"), (8, 6, 4, 2), strict=True)),
        "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
        "defensive_contribution": {"GKP": 0, "DEF": 9, "MID": 5, "FWD": 3},
    }
    document = {
        "game_config": {
            "scoring": scoring,
            "rules": {
                "squad_squadsize": 15,
                "squad_squadplay": 11,
                "squad_team_limit": 3,
                "squad_total_spend": 1000,
                "max_extra_free_transfers": 4,
                "transfers_cap": 20,
                "transfers_sell_on_fee": 0.5,
                "element_sell_at_purchase_price": False,
            },
        },
        "chips": [
            {"name": name, "number": 1, "start_event": 2, "stop_event": 38, "chip_type": kind}
            for name, kind in (
                ("wildcard", "transfer"),
                ("freehit", "transfer"),
                ("bboost", "team"),
                ("3xc", "team"),
            )
        ],
    }
    metadata = write_snapshot(
        tmp_path,
        source="invented-point-rules",
        captured_at_utc="2026-09-22T12:00:00Z",
        payloads={BOOTSTRAP_PAYLOAD: json.dumps(document).encode("utf-8")},
    )
    return read_season_rules(
        read_snapshot(tmp_path, metadata.snapshot_id), season="2026-27"
    ).scoring


def _weights(rules: ScoringRules, position: str) -> PointCoefficients:
    # Source-position translation belongs to this caller, never the leaf algebra.
    source_position = "GKP" if position == "GK" else position
    return PointCoefficients(
        rules.short_play,
        rules.long_play,
        rules.goals_scored[source_position],
        rules.assists,
        rules.clean_sheets[source_position],
        rules.defensive_contribution[source_position],
    )


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("custom", (False, True))
def test_invented_capture_weights_survive_without_native_defaults(
    tmp_path: Path, position: str, custom: bool
) -> None:
    rules = _capture_rules(tmp_path, custom=custom)
    weights = _weights(rules, position)
    moments = ComponentMoments(0.75, 0.5, 0.21, 0.13, 0.2, 0.1, -0.6)
    result = raw_points(moments, weights)
    key = "GKP" if position == "GK" else position
    # Hand-derived appearance masses: 1/4 no play, 1/4 short play, 1/2 qualifying play.
    # The action-world reconstruction follows in the next test.
    expected = math.fsum(
        (
            0.25 * rules.short_play,
            0.5 * rules.long_play,
            0.21 * rules.goals_scored[key],
            0.13 * rules.assists,
            0.2 * rules.clean_sheets[key],
            0.1 * rules.defensive_contribution[key],
            -0.6,
        )
    )
    assert result.raw_expected_points == expected
    assert result.moments is moments
    assert result.coefficients is weights


@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("custom", (False, True))
def test_invented_capture_weights_reproduce_explicit_action_worlds(
    tmp_path: Path, position: str, custom: bool
) -> None:
    rules = _capture_rules(tmp_path, custom=custom)
    key = "GKP" if position == "GK" else position
    # Probability, credited minutes, goals, assists, clean sheet, DEFCON award and
    # signed residual points. Clean sheets occur only in qualifying-minute worlds.
    worlds = (
        (0.25, 0, 0, 0, False, False, 0),
        (0.15, 30, 1, 0, False, False, -1),
        (0.10, 30, 0, 1, False, True, 0),
        (0.20, 90, 0, 0, True, True, 3),
        (0.30, 75, 1, 1, False, False, -2),
    )

    def mass(select: int) -> float:
        return math.fsum(world[0] * float(world[select]) for world in worlds)

    moments = ComponentMoments(
        math.fsum(world[0] for world in worlds if world[1] > 0),
        math.fsum(world[0] for world in worlds if world[1] >= 60),
        mass(2),
        mass(3),
        mass(4),
        mass(5),
        mass(6),
    )
    realized = []
    for probability, minutes, goals, assists, clean, dc, residual in worlds:
        appearance = 0 if minutes == 0 else rules.short_play if minutes < 60 else rules.long_play
        points = (
            appearance
            + rules.goals_scored[key] * goals
            + rules.assists * assists
            + rules.clean_sheets[key] * clean
            + rules.defensive_contribution[key] * dc
            + residual
        )
        realized.append(probability * points)
    result = raw_points(moments, _weights(rules, position))
    assert result.raw_expected_points == pytest.approx(math.fsum(realized), rel=1e-12, abs=1e-12)


@pytest.mark.parametrize("season", ("2023-24", "2024-25", "2025-26"))
@pytest.mark.parametrize("position", POSITIONS)
@pytest.mark.parametrize("conditional_residual", (0.0, -0.8, -30.0))
@pytest.mark.parametrize(
    "support",
    ((0.25, 0.25, 0.25, 0.25), (0.8, 0.0, 0.2, 0.0), (0.999999, 0.0, 0.000001, 0.0)),
)
def test_accepted_native_raw_algebra_matches_with_explicit_caller_conversion(
    season: str, position: str, conditional_residual: float, support: tuple[float, ...]
) -> None:
    frame = pd.DataFrame(
        [
            {
                "position": position,
                "opponent_goal_rate": 1.4,
                "defcon_rate90": 8.0,
                "defcon_dispersion": 4.0,
                "goals": 0.21,
                "assists": 0.13,
                "residual_if_appearance": conditional_residual,
                **{f"minute_probability_{b}": support[b] for b in range(4)},
                **dict(
                    zip(
                        (f"minute_value_{b}" for b in range(4)),
                        (0.0, 30.0, 75.0, 90.0),
                        strict=True,
                    )
                ),
            }
        ]
    )
    frame.attrs["season"] = season
    native = _score_components(frame).iloc[0]
    # These explicit test weights reproduce accepted native version boundaries.
    # They do not authenticate real historical rules or infer a new season policy.
    goal = {"GK": 10 if season >= "2024-25" else 6, "DEF": 6, "MID": 5, "FWD": 4}
    clean = {"GK": 4, "DEF": 4, "MID": 1, "FWD": 0}
    weights = PointCoefficients(
        1, 2, goal[position], 3, clean[position], 2 if season >= "2025-26" else 0
    )
    moments = ComponentMoments(
        native.appearance_probability,
        native.p60,
        native.goals,
        native.assists,
        native.clean_sheet_probability,
        native.defcon_probability,
        native.appearance_probability * conditional_residual,
        # The accepted producer uses complement and subset-sum arithmetic.
        # Declare its binary rounding budget without rewriting either supplied moment.
        support_roundoff=2 * math.ulp(1.0),
    )
    result = raw_points(moments, weights)
    assert result.raw_expected_points == pytest.approx(
        native.raw_expected_points, abs=1e-12, rel=1e-12
    )
    assert clip_points(result.raw_expected_points) == pytest.approx(
        native.expected_points, abs=1e-12, rel=1e-12
    )
    assert result.residual_points == native.appearance_probability * conditional_residual
    assert result.moments.appearance_probability == native.appearance_probability
    assert result.moments.p60 == native.p60


def test_nonlinear_state_clean_sheet_moment_survives_the_point_boundary() -> None:
    # Equal physical exposure, two conditional opponent-rate states.
    # E[exp(-lambda)] differs from exp(-E[lambda]).
    mixed_clean = 0.25 * math.exp(-0.1) + 0.25 * math.exp(-3.0)
    replaced_clean = 0.5 * math.exp(-1.55)
    assert abs(mixed_clean - replaced_clean) > 0.1
    moments = ComponentMoments(0.75, 0.5, 0.2, 0.1, mixed_clean, 0.08, -0.75)
    result = raw_points(moments, PointCoefficients(1, 2, 6, 3, 4, 2))
    assert result.clean_sheet_points == 4 * mixed_clean
    assert result.defcon_points == 2 * 0.08
    assert result.moments.clean_sheet_probability == mixed_clean
    assert result.raw_expected_points != pytest.approx(
        0.75 + 0.5 + 6 * 0.2 + 3 * 0.1 + 4 * replaced_clean + 2 * 0.08 - 0.75
    )


def test_native_aggregate_clipping_scope_is_explicit_and_not_moved_into_worlds() -> None:
    weights = PointCoefficients(1, 2, 6, 3, 4, 2)
    bad = raw_points(ComponentMoments(1, 0, 0, 0, 0, 0, -3), weights).raw_expected_points
    good = raw_points(ComponentMoments(1, 0, 0, 0, 0, 0, 1), weights).raw_expected_points
    assert (bad, good) == (-2, 2)
    mixture = raw_points(ComponentMoments(1, 0, 0, 0, 0, 0, -1), weights)
    assert mixture.raw_expected_points == (bad + good) / 2 == 0
    assert clip_points(mixture.raw_expected_points) == 0
    assert (clip_points(bad) + clip_points(good)) / 2 == 1


def test_zero_appearance_card_only_residual_does_not_invent_autosub_eligibility() -> None:
    moments = ComponentMoments(0, 0, 0, 0, 0, 0, -3)
    result = raw_points(moments, PointCoefficients(1, 2, 6, 3, 4, 2))
    assert result.raw_expected_points == -3
    assert result.moments.appearance_probability == 0
    assert clip_points(result.raw_expected_points) == 0
