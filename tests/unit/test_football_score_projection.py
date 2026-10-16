"""Clock-source exclusions and independent native-survival preservation."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import FrozenInstanceError, asdict, replace
from typing import Any

import pytest
from tests.unit.test_football_score_state import fit, fixture, observation

from squadopt.features.football_score_projection import (
    ScoreDurationForecast,
    ScoreNativePlayer,
    ScorePastDuration,
    forecast_physical_duration,
    project_score_intervals,
)
from squadopt.features.football_score_state_inputs import validate_score_fixture

DECISION = "2026-10-10T12:00:00Z"
GENERATED = "2026-10-10T11:30:00Z"


def history() -> tuple[ScorePastDuration, ...]:
    return (
        ScorePastDuration(
            "2025-26",
            1,
            100,
            "2025-08-15T19:00:00Z",
            "2025-08-16T01:00:00Z",
            (2880, 3120),
            "a" * 64,
            "b" * 64,
        ),
        ScorePastDuration(
            "2025-26",
            2,
            101,
            "2025-08-22T19:00:00Z",
            "2025-08-23T01:00:00Z",
            (3000, 3120),
            "c" * 64,
            "d" * 64,
        ),
    )


def forecast() -> ScoreDurationForecast:
    return ScoreDurationForecast(
        "2026-27",
        6,
        1,
        "2026-10-10T10:00:00Z",
        "2026-10-10T11:00:00Z",
        "2026-10-10T11:15:00Z",
        history(),
    )


def players() -> tuple[ScoreNativePlayer, ...]:
    return tuple(
        ScoreNativePlayer(
            code,
            1 if code <= 2 else 2,
            "DEF",
            (0.15, 0.1, 0.2, 0.25, 0.1, 0.2, 0),
            (0, 16.5, 75.2, 90, 12.1, 65.7, 90),
        )
        for code in range(1, 5)
    )


def project(native=None, clock=None, **options):
    return project_score_intervals(
        players() if native is None else native,
        forecast() if clock is None else clock,
        **dict(
            native_basis_sha256="e" * 64, decision_at=DECISION, generated_at=GENERATED, **options
        ),
    )


def test_exact_native_atoms_and_independently_computed_interval_endpoints() -> None:
    original = players()
    result = project(original)
    assert result.receipt.forecast_duration == 101
    for native, projected in zip(original, result.players, strict=True):
        assert projected.probabilities == native.probabilities
        assert projected.credited_minutes == native.credited_minutes
        assert projected.physical_on[:4] == (0, 0, 0, 0)
        assert projected.physical_off[:4] == pytest.approx(
            (0, 18.516666666666666, 84.3911111111111, 101)
        )
        assert projected.physical_off[4:] == (101, 101, 101)
        assert projected.physical_on[4:] == pytest.approx((87.42111111111112, 27.27, 0))
        assert projected.exit_policies == (
            "not_playing",
            "normal_substitution",
            "normal_substitution",
            "full_time",
            "full_time",
            "full_time",
            "full_time",
        )
    raw = json.dumps(
        asdict(result.receipt), sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    assert hashlib.sha256(raw).hexdigest() == result.receipt_sha256
    with pytest.raises(FrozenInstanceError):
        result.receipt.forecast_duration = 90  # type: ignore[misc]


def test_positive_cameo_refuses_a_physical_interval_lost_to_float_rounding() -> None:
    native = players()
    minutes = (*native[0].credited_minutes[:4], 1e-15, *native[0].credited_minutes[5:])
    changed = (replace(native[0], credited_minutes=minutes), *native[1:])
    with pytest.raises(ValueError, match="Positive exposure"):
        project(changed)


@pytest.mark.parametrize("horizon", [90, 101, 180])
def test_zero_score_chain_preserves_native_atom_survival_and_weighted_eligibility(
    horizon: int,
) -> None:
    clock = replace(
        forecast(), history=(replace(history()[0], period_seconds=(horizon * 30, horizon * 30)),)
    )
    projected = project(clock=clock)
    source = replace(fixture(target=True), forecast_duration=horizon, players=projected.players)
    validate_score_fixture(source)
    model = fit((observation(),))
    result = model.predict(source, zero_coefficients=True)
    for native, survived in zip(players(), result.player_survival, strict=True):
        opposing = source.native_away_goals if native.club_code == 1 else source.native_home_goals
        expected = tuple(
            0 if i == 0 else math.exp(-opposing * m / 90)
            for i, m in enumerate(native.credited_minutes)
        )
        assert survived.survival == pytest.approx(expected, abs=result.mass_error_bound)
        actual_weighted = sum(
            p * s
            for p, s, m in zip(
                native.probabilities, survived.survival, native.credited_minutes, strict=True
            )
            if m >= 60
        )
        expected_weighted = sum(
            p * math.exp(-opposing * m / 90)
            for p, m in zip(native.probabilities, native.credited_minutes, strict=True)
            if m >= 60
        )
        assert actual_weighted == pytest.approx(expected_weighted, abs=result.mass_error_bound)


@pytest.mark.parametrize(
    "changes",
    [
        {"target_season": "2026-28"},
        {"target_season": "2025-26"},
        {"target_gameweek": True},
        {"target_gameweek": 39},
        {"target_fixture_id": 0},
        {"duration_policy": "actual_target_duration"},
        {"history": ()},
        {"history": list(history())},
        {"history": (history()[0], history()[0])},
        {"feature_cutoff": "2026-10-10T13:00:00Z"},
        {"source_captured_at": "2026-10-10T13:00:00Z"},
        {"source_captured_at": "2025-08-01T00:00:00Z"},
        {"generated_at": "2026-10-10T13:00:00Z"},
    ],
)
def test_invalid_population_and_predecision_clocks_refuse(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        forecast_physical_duration(replace(forecast(), **changes), decision_at=DECISION)


@pytest.mark.parametrize(
    "changes",
    [
        {"season": "2027-28"},
        {"season": "2026-27", "gameweek": 6},
        {"season": "2026-27", "gameweek": 7},
        {"season": "2026-27", "gameweek": 1, "fixture_id": 1},
        {"gameweek": True},
        {"period_seconds": (2699, 3000)},
        {"period_seconds": (2880.0, 3120)},
        {"period_seconds": (True, 3120)},
        {"period_seconds": (5401, 3000)},
        {"period_seconds": (3000,)},
        {"period_seconds": [2880, 3120]},
        {"source_sha256": "bad"},
        {"completion_sha256": "a" * 63},
        {"completed_by": "2026-10-10T10:00:01Z"},
        {"completed_by": "2025-08-15T18:00:00Z"},
        {"kickoff": "2025-06-30T19:00:00Z"},
    ],
)
def test_malformed_or_target_history_refuses(changes: dict[str, Any]) -> None:
    if "season" in changes:
        year = changes["season"][:4]
        changes = {
            "kickoff": f"{year}-08-15T19:00:00Z",
            "completed_by": f"{year}-08-16T01:00:00Z",
            **changes,
        }
    with pytest.raises(ValueError):
        forecast_physical_duration(
            replace(forecast(), history=(replace(history()[0], **changes),)), decision_at=DECISION
        )


@pytest.mark.parametrize(
    "changes",
    [
        {"player_code": True},
        {"club_code": 0},
        {"position": "unknown"},
        {"probabilities": (0.15, 0.1, 0.2, 0.25, 0.1, 0.1, 0.1)},
        {"probabilities": (0.15, 0.1, 0.2, 0.25, 0.1, 0.1, 0)},
        {"probabilities": (True, 0, 0, 0, 0, 0, 0)},
        {"probabilities": (float("nan"), 0, 0, 0, 0, 0, 0)},
        {"credited_minutes": (0, 16.5, 75.2, 91, 12.1, 65.7, 90)},
        {"credited_minutes": (0, 16.5, 75.2, 90, 12.1, 65.7, 91)},
        {"credited_minutes": (0, 16.5, 75.2, 89, 12.1, 65.7, 90)},
        {"credited_minutes": (0, 16.5, 75.2, 90)},
    ],
)
def test_native_atoms_are_refused_instead_of_repaired(changes: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        project((replace(players()[0], **changes),))


def test_duplicate_players_and_postdecision_generation_refuse() -> None:
    with pytest.raises(ValueError):
        project((players()[0], players()[0]))
    with pytest.raises(ValueError):
        project_score_intervals(
            players(),
            forecast(),
            native_basis_sha256="e" * 64,
            decision_at=DECISION,
            generated_at="2026-10-10T12:00:01Z",
        )


def test_news_minute_reprojection_changes_receipt_and_retains_new_native_values() -> None:
    before = project()
    native = players()
    changed = (replace(native[0], credited_minutes=(0, 20, 70, 90, 15, 60, 90)), *native[1:])
    after = project_score_intervals(
        changed,
        forecast(),
        native_basis_sha256="f" * 64,
        decision_at=DECISION,
        generated_at=GENERATED,
    )
    assert before.receipt_sha256 != after.receipt_sha256
    assert before.receipt.native_players_sha256 != after.receipt.native_players_sha256
    assert after.players[0].probabilities == native[0].probabilities
    assert after.players[0].credited_minutes == changed[0].credited_minutes
    assert after.receipt.eligibility_applied is False
