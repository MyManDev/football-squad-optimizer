"""Final weekly law and score-chain semantics survive the public artifact reader."""

import json
from copy import deepcopy

import numpy as np
import pandas as pd
import pytest
from tests.unit.test_football_minute_integration import world
from tests.unit.test_joint_role_minute_evidence import joint_documents

from squadopt.live.football_artifact import forecast_digest, read_football_forecast
from squadopt.live.minute_evidence import _score_components, _validate_components
from squadopt.prediction.football_capabilities import (
    COMPOSITE_ACTIVE_HEADS,
    COMPOSITE_AVAILABILITY_POLICY,
    COMPOSITE_FEATURE_VERSION,
    COMPOSITE_MODEL_VERSION,
    COMPOSITE_REPROJECTION_VERSION,
)
from squadopt.prediction.football_composite_contract import (
    COMPOSITE_ASSET_ROLES,
    composite_weekly_chances,
)


def _document():
    _, inputs, _, basis = world()
    original = basis.served
    first = [row for row in original["rows"] if row["gameweek"] == 6]
    rows = [{**row, "gameweek": week} for week in range(6, 11) for row in first]
    document = {
        **original,
        "model_version": COMPOSITE_MODEL_VERSION,
        "feature_contract_version": COMPOSITE_FEATURE_VERSION,
        "availability_application": COMPOSITE_AVAILABILITY_POLICY,
        "rows": rows,
        "composite_metadata": {
            "version": COMPOSITE_REPROJECTION_VERSION,
            "active_heads": list(COMPOSITE_ACTIVE_HEADS),
            "availability_application": COMPOSITE_AVAILABILITY_POLICY,
            "basis_sha256": "a" * 64,
            "fixture_receipts_sha256": "b" * 64,
            "generated_at": "2026-09-22T12:05:00+00:00",
            "decision_at": "2026-09-22T12:06:00+00:00",
            "model_artifacts": [
                {
                    "role": role,
                    "kind": "retained_flag_result" if role == "flags" else "compact_model",
                    "sha256": "c" * 64,
                    "fit_sha256": "d" * 64,
                }
                for role in COMPOSITE_ASSET_ROLES
            ],
            "weekly_laws": [
                {
                    "gameweek": row["gameweek"],
                    "player_code": row["player_id"],
                    "appearance_probability": row["appearance_probability"],
                    "fixture_ids": [row["gameweek"] * 10 + 1],
                    "sha256": "e" * 64,
                }
                for row in rows
            ],
        },
    }
    document["fingerprint"] = forecast_digest(document)
    return document, inputs


def test_all_five_weeks_keep_final_points_and_q_without_second_capture_multiplier(tmp_path):
    document, inputs = _document()
    path = tmp_path / "composite.json"
    path.write_text(json.dumps(document))
    loaded = read_football_forecast(path, inputs)
    original = pd.DataFrame(document["rows"])
    np.testing.assert_array_equal(loaded.horizon.table.expected_points, original.expected_points)
    np.testing.assert_array_equal(
        loaded.horizon.table.appearance_probability, original.appearance_probability
    )
    assert (
        loaded.projection.diagnostics["availability_application"] == COMPOSITE_AVAILABILITY_POLICY
    )
    assert set(inputs.availability.chance_of_playing) == {50.0}
    for length in (1, 3, 5):
        assert len(loaded.build_horizon(tuple(range(6, 6 + length))).table) == length * len(
            inputs.players
        )


@pytest.mark.parametrize(
    "damage", ["count_head", "missing_family", "duplicated_law", "q", "late", "boolean"]
)
def test_rehashing_does_not_admit_invalid_family_or_weekly_receipts(tmp_path, damage):
    document, inputs = _document()
    meta = document["composite_metadata"]
    if damage == "count_head":
        meta["active_heads"].append("tactical_team_rates")
    elif damage == "missing_family":
        meta["model_artifacts"].pop()
    elif damage == "duplicated_law":
        meta["weekly_laws"][1] = deepcopy(meta["weekly_laws"][0])
    elif damage == "q":
        document["rows"][0]["appearance_probability"] *= 0.5
    elif damage == "late":
        meta["decision_at"] = inputs.deadline.deadline_utc
    else:
        meta["weekly_laws"][0]["player_code"] = True
    document["fingerprint"] = forecast_digest(document)
    path = tmp_path / "composite.json"
    path.write_text(json.dumps(document))
    with pytest.raises(ValueError):
        read_football_forecast(path, inputs)


def test_legacy_forecast_does_not_take_artifact_supplied_capabilities():
    document, _ = _document()
    document["model_version"] = "untrusted_version"
    assert composite_weekly_chances(document) is None


def test_score_process_survival_replaces_single_rate_cs_and_validates_weighted_atoms():
    served, companion, _, _ = joint_documents()
    frame = pd.DataFrame(companion["rows"])
    frame.attrs.update(season=served["season"], joint_role=True, score_process=True)
    values = [1.0, 0.93, 0.71, 0.60, 0.96, 0.82, 0.60]
    for b, value in enumerate(values):
        frame[f"score_survival_{b}"] = value
    expected = sum(
        frame[f"{role}_minute_probability_{b}"] * values[offset + b]
        for role, offset in (("start", 0), ("cameo", 3))
        for b in (2, 3)
    )
    revised = _score_components(frame)
    np.testing.assert_allclose(revised.clean_sheet_probability, expected, atol=1e-15, rtol=0)
    assert not np.allclose(revised.clean_sheet_probability, frame.clean_sheet_probability)
    _validate_components(revised, served["season"], joint_role=True, score_process=True)
    with pytest.raises(ValueError, match="clean_sheet_probability"):
        _validate_components(revised.copy(), served["season"], joint_role=True)
    changed = revised.copy()
    changed.loc[0, "score_survival_2"] = 0.2
    with pytest.raises(ValueError, match="clean_sheet_probability"):
        _validate_components(changed, served["season"], joint_role=True, score_process=True)
