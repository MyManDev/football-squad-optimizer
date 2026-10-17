"""The gradient-boosting candidate of the Phase C control components.

The candidate keeps the control's rows, features, targets and routes and swaps the three
linear estimators for histogram gradient-boosted ensembles with declared constants. These
tests pin the contract: its own model version, equal weighting only, determinism, the same
bounds and routes as the control, and the v1 export refusing it while the v2 export writes a
separately named table the development reader and the comparison accept.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from scripts.compare_component_oof_development import main as compare_main
from scripts.export_component_oof import DEVELOPMENT_OOF_CONTRACT_VERSION, main
from tests.unit.test_export_component_oof_v2 import LOCKED, NEW, OLD, THREE, _run_export

from squadopt.evaluation import read_phase_c_component_handoff
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    EQUAL_WEIGHTING,
    GRADIENT_BOOSTING_ESTIMATOR,
    GRADIENT_BOOSTING_MODEL_VERSION,
    LINEAR_ESTIMATOR,
    ComponentModelConfig,
    SeasonAgeWeighting,
    fit_component_models,
    predict_components,
)
from squadopt.prediction.config import PredictionConfigurationError

FEATURES = ("minutes_last_3", "price_tenths", "fixture_count")
SMALL = ComponentModelConfig(
    minimum_training_rows=10, estimator=GRADIENT_BOOSTING_ESTIMATOR, boosting_iterations=20
)


def _training(rows: int = 240, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    minutes = rng.uniform(0, 90, rows)
    price = rng.uniform(40, 130, rows)
    appearance = (rng.uniform(0, 1, rows) < 0.3 + 0.6 * minutes / 90).astype("int64")
    conditional_minutes = np.clip(minutes + rng.normal(0, 10, rows), 1, 90)
    return pd.DataFrame(
        {
            "season": ["2023-24"] * (rows // 2) + ["2024-25"] * (rows - rows // 2),
            "minutes_last_3": minutes,
            "price_tenths": price,
            "fixture_count": np.where(rng.uniform(0, 1, rows) < 0.1, 2, 1),
            "appearance_target": appearance,
            "minutes_target": np.where(appearance == 1, conditional_minutes, np.nan),
            "points_target": np.where(appearance == 1, rng.poisson(3, rows), np.nan),
        }
    )


def test_the_candidate_carries_its_own_version_and_estimator() -> None:
    fitted = fit_component_models(_training(), feature_columns=FEATURES, config=SMALL)
    assert fitted is not None
    assert fitted.model_version == GRADIENT_BOOSTING_MODEL_VERSION
    assert fitted.estimator == GRADIENT_BOOSTING_ESTIMATOR
    assert fitted.weighting == EQUAL_WEIGHTING
    control = fit_component_models(
        _training(),
        feature_columns=FEATURES,
        config=ComponentModelConfig(minimum_training_rows=10),
    )
    assert control is not None
    assert control.model_version == COMPONENT_MODEL_VERSION
    assert control.estimator == LINEAR_ESTIMATOR


def test_the_candidate_refuses_season_weighting_and_unknown_estimators() -> None:
    with pytest.raises(PredictionConfigurationError):
        fit_component_models(
            _training(),
            feature_columns=FEATURES,
            config=SMALL,
            weighting=SeasonAgeWeighting(target_season="2024-25"),
        )
    with pytest.raises(PredictionConfigurationError):
        ComponentModelConfig(estimator="random_forest")
    with pytest.raises(PredictionConfigurationError):
        ComponentModelConfig(boosting_iterations=0)
    with pytest.raises(PredictionConfigurationError):
        ComponentModelConfig(boosting_learning_rate=0.0)


def test_the_candidate_is_deterministic_and_keeps_the_control_bounds_and_routes() -> None:
    training = _training()
    scoring = _training(rows=60, seed=7)
    scoring.loc[0, "minutes_last_3"] = np.nan  # one incomplete row takes the fallback route
    scoring.loc[1, "fixture_count"] = 0  # one blank gameweek
    first = fit_component_models(training, feature_columns=FEATURES, config=SMALL)
    second = fit_component_models(training, feature_columns=FEATURES, config=SMALL)
    assert first is not None and second is not None
    left = predict_components(first, scoring, feature_columns=FEATURES)
    right = predict_components(second, scoring, feature_columns=FEATURES)
    assert_frame_equal(left, right)
    assert left.loc[0, "composition_route"] == "direct_control"
    assert pd.isna(left.loc[0, "appearance_probability"])
    assert left.loc[1, "composition_route"] == "component_model"
    assert float(left.loc[1, "expected_minutes_if_appearance"]) == 0.0
    modelled = left.loc[left["composition_route"] == "component_model"]
    probability = pd.to_numeric(modelled["appearance_probability"]).astype("float64")
    assert probability.between(0.0, 1.0).all()
    minutes = pd.to_numeric(modelled["expected_minutes_if_appearance"]).astype("float64")
    ceiling = scoring.loc[modelled.index, "fixture_count"].astype("float64") * 90.0
    assert (minutes <= ceiling + 1e-9).all()
    assert (minutes >= 0.0).all()
    points = pd.to_numeric(modelled["expected_points_if_appearance"]).astype("float64")
    assert (points >= 0.0).all()


def test_the_v1_contract_refuses_the_gradient_boosting_candidate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "export_component_oof",
            "--estimator",
            GRADIENT_BOOSTING_ESTIMATOR,
            "--seasons",
            f"{OLD},{NEW}",
        ],
    )
    assert main() == 1
    assert "--development-scope v2" in capsys.readouterr().out


def test_the_v2_weighted_arm_refuses_the_gradient_boosting_estimator(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "export_component_oof",
            "--development-scope",
            "v2",
            "--season-weighting",
            "season_half_life",
            "--estimator",
            GRADIENT_BOOSTING_ESTIMATOR,
        ],
    )
    assert main() == 1
    assert "equal weighting only" in capsys.readouterr().out


def test_the_v2_export_writes_the_candidate_the_reader_and_the_comparison_accept(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seasons = ",".join(THREE)
    control = _run_export(
        tmp_path / "control", monkeypatch, "--development-scope", "v2", "--seasons", seasons
    )
    candidate = _run_export(
        tmp_path / "candidate",
        monkeypatch,
        "--development-scope",
        "v2",
        "--estimator",
        GRADIENT_BOOSTING_ESTIMATOR,
        "--seasons",
        seasons,
    )
    table_path, _, manifest_path = candidate
    assert table_path.name == f"{DEVELOPMENT_OOF_CONTRACT_VERSION}_equal_gradient_boosting.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["model_version"] == GRADIENT_BOOSTING_MODEL_VERSION
    assert manifest["weighting"]["label"] == EQUAL_WEIGHTING
    assert manifest["weighting"]["model_version"] == GRADIENT_BOOSTING_MODEL_VERSION
    assert manifest["estimator"]["name"] == GRADIENT_BOOSTING_ESTIMATOR
    assert manifest["estimator"]["constants"]["early_stopping"] is False
    assert "--estimator gradient_boosting" in manifest["reproduce"]
    assert all(record["estimator"] == GRADIENT_BOOSTING_ESTIMATOR for record in manifest["folds"])
    handoff = read_phase_c_component_handoff(
        *candidate, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
    )
    assert handoff.model_version == GRADIENT_BOOSTING_MODEL_VERSION
    control_manifest = json.loads(control[2].read_text(encoding="utf-8"))
    assert control_manifest["estimator"]["name"] == LINEAR_ESTIMATOR
    assert control_manifest["model_version"] == COMPONENT_MODEL_VERSION

    artifact_dir = tmp_path / "pair"
    artifact_dir.mkdir()
    for paths in (control, candidate):
        for path in paths:
            (artifact_dir / path.name).write_bytes(path.read_bytes())
    arguments = ["--artifact-dir", str(artifact_dir), "--candidate-arm", "gradient_boosting"]
    assert compare_main(arguments) == 0
    report_path = artifact_dir / "comparison_gradient_boosting" / "comparison.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["candidate_arm"] == "gradient_boosting"
    assert report["arms"]["candidate"]["model_version"] == GRADIENT_BOOSTING_MODEL_VERSION
    assert report["primary_season"]["season"] == LOCKED
    assert report["verdict"]["verdict"] in {"candidate_preferred", "no_selection"}
    # The default arm still expects the weighted candidate and refuses the boosted table.
    refused = ["--artifact-dir", str(artifact_dir), "--candidate", table_path.name[:-4]]
    assert compare_main(refused) == 1
