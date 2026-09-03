"""Behavioural tests for the operational Top-100 evidence rule."""

import pandas as pd
import pytest

from squadopt.prediction.config import PredictionConfigurationError
from squadopt.prediction.elite_evidence import (
    ELITE_EVIDENCE_POLICY_VERSION,
    apply_elite_evidence,
)

SEASON = "2026-27"
GAMEWEEK = 3
DEADLINE = "2026-09-04T17:30:00Z"
EVIDENCE_CAPTURED_AT = "2026-09-01T16:37:12Z"
DECISION_CAPTURED_AT = "2026-09-03T12:00:00Z"


def _projection() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": list(range(101, 113)),
            "name": [f"Player {value}" for value in range(101, 113)],
            "expected_points": [4.0, *([5.0] * 11)],
        }
    )


def _evidence() -> pd.DataFrame:
    player_ids = list(range(101, 113))
    table = pd.DataFrame(
        {
            "season": [SEASON] * 12,
            "target_gameweek": [GAMEWEEK] * 12,
            "captured_at_utc": [EVIDENCE_CAPTURED_AT] * 12,
            "deadline_timestamp_utc": [DEADLINE] * 12,
            "player_id": player_ids,
            "elite_cohort_size": [100] * 12,
            "elite_members_observed": [100] * 12,
            "elite_start_count_lag1": [0, *([100] * 11)],
            "elite_start_share_lag1": [0.0, *([1.0] * 11)],
            "elite_evidence_observed": [True] * 12,
        }
    )
    table.attrs.update(
        {
            "elite_members_missing_picks": 0,
            "unmapped_picked_elements": (),
            "table_sha256": "a" * 64,
        }
    )
    return table


def _apply(projection: pd.DataFrame | None = None, evidence: pd.DataFrame | None = None):
    return apply_elite_evidence(
        _projection() if projection is None else projection,
        _evidence() if evidence is None else evidence,
        season=SEASON,
        target_gameweek=GAMEWEEK,
        deadline_timestamp_utc=DEADLINE,
        decision_captured_at_utc=DECISION_CAPTURED_AT,
    )


def test_top100_xi_support_has_a_bounded_uplift_and_zero_is_not_missing() -> None:
    result = _apply()

    assert result.table["expected_points"].tolist() == pytest.approx([4.0, *([5.25] * 11)])
    assert result.diagnostics["elite_evidence_policy_version"] == ELITE_EVIDENCE_POLICY_VERSION
    assert result.diagnostics["elite_evidence_players_uplifted"] == 11
    assert result.diagnostics["elite_evidence_maximum_relative_uplift"] == 0.05


def test_inputs_are_not_mutated_and_row_order_does_not_change_player_values() -> None:
    projection = _projection()
    evidence = _evidence()
    projection_before = projection.copy(deep=True)
    evidence_before = evidence.copy(deep=True)

    first = _apply(projection, evidence)
    second = _apply(projection.iloc[::-1].reset_index(drop=True), evidence.iloc[::-1])

    pd.testing.assert_frame_equal(projection, projection_before)
    pd.testing.assert_frame_equal(evidence, evidence_before)
    assert first.table.set_index("player_id")["expected_points"].to_dict() == pytest.approx(
        second.table.set_index("player_id")["expected_points"].to_dict()
    )


@pytest.mark.parametrize(
    ("column", "value", "match"),
    [
        ("season", "2025-26", "season"),
        ("target_gameweek", 4, "target_gameweek"),
        ("deadline_timestamp_utc", "2026-09-05T17:30:00Z", "deadline"),
    ],
)
def test_evidence_must_describe_the_decision(column: str, value: object, match: str) -> None:
    evidence = _evidence()
    evidence[column] = value

    with pytest.raises(PredictionConfigurationError, match=match):
        _apply(evidence=evidence)


def test_the_operational_policy_requires_a_complete_top100() -> None:
    evidence = _evidence()
    evidence["elite_members_observed"] = 99

    with pytest.raises(PredictionConfigurationError, match="100 observed"):
        _apply(evidence=evidence)


def test_count_share_disagreement_is_rejected() -> None:
    evidence = _evidence()
    evidence.loc[evidence["player_id"].eq(101), "elite_start_share_lag1"] = 0.99

    with pytest.raises(PredictionConfigurationError, match="shares"):
        _apply(evidence=evidence)


def test_all_top100_xi_selections_must_be_accounted_for() -> None:
    evidence = _evidence()
    evidence.loc[evidence["player_id"].eq(101), "elite_start_count_lag1"] = 99
    evidence.loc[evidence["player_id"].eq(101), "elite_start_share_lag1"] = 0.99

    with pytest.raises(PredictionConfigurationError, match="sum to 11"):
        _apply(evidence=evidence)


def test_a_roster_player_missing_from_evidence_keeps_the_control_value() -> None:
    evidence = _evidence()
    evidence.loc[evidence["player_id"].eq(112), "player_id"] = 303

    result = _apply(evidence=evidence)

    assert result.table.set_index("player_id").loc[112, "expected_points"] == 5.0
    assert result.diagnostics["elite_evidence_players_missing"] == 1
    assert result.diagnostics["elite_evidence_players_not_on_roster"] == 1


def test_boolean_player_identifiers_are_rejected() -> None:
    projection = _projection()
    projection["player_id"] = projection["player_id"].astype("object")
    projection.loc[0, "player_id"] = True

    with pytest.raises(PredictionConfigurationError, match="non-boolean integers"):
        _apply(projection=projection)


def test_evidence_captured_after_the_decision_snapshot_is_rejected() -> None:
    evidence = _evidence()
    evidence["captured_at_utc"] = "2026-09-03T13:00:00Z"

    with pytest.raises(PredictionConfigurationError, match="after the decision snapshot"):
        _apply(evidence=evidence)


def test_invalid_requested_evidence_never_silently_falls_back() -> None:
    evidence = _evidence()
    evidence.attrs["elite_members_missing_picks"] = 1

    with pytest.raises(PredictionConfigurationError, match="missing member picks"):
        _apply(evidence=evidence)
