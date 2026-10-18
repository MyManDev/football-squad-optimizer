"""The regime-gated candidate of the Phase C control components.

The candidate keeps the control's rows, features, targets and routes, fits one served-pair
expert set per declared regime (fixture regime by rule era) and mixes them with a
multinomial logistic gate on the v1 features plus the regime terms. These tests pin the
contract: its own model version, equal weighting only, the target season it needs,
determinism, the control's bounds and routes, a one-regime fit equal to the linear control,
an absent expert's mass renormalized away, a gate that routes each row to its own regime's
expert, and the v2 export writing a separately named table the development reader and the
comparison accept while the v1 export refuses it.
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
from tests.unit.test_export_component_oof_v2 import NEW, OLD, THREE, _run_export

from squadopt.evaluation import read_phase_c_component_handoff
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    DOUBLE_DEFCON_REGIME,
    DOUBLE_PRE_DEFCON_REGIME,
    EQUAL_WEIGHTING,
    REGIME_ESTIMATOR,
    REGIME_GATE_TERMS,
    REGIME_LABELS,
    REGIME_MODEL_VERSION,
    SINGLE_DEFCON_REGIME,
    SINGLE_PRE_DEFCON_REGIME,
    ComponentModelConfig,
    RegimeMixture,
    SeasonAgeWeighting,
    fit_component_models,
    predict_components,
    regime_design,
    regime_expert_summary,
    regime_labels,
)
from squadopt.prediction.config import PredictionConfigurationError

FEATURES = ("minutes_last_3", "price_tenths", "fixture_count")
SMALL = ComponentModelConfig(minimum_training_rows=10, estimator=REGIME_ESTIMATOR)
LINEAR = ComponentModelConfig(minimum_training_rows=10)
TARGET = "2025-26"


def _training(
    rows: int = 600,
    seed: int = 0,
    seasons: tuple[str, str] = ("2024-25", TARGET),
    double_share: float = 0.2,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    minutes = rng.uniform(0, 90, rows)
    price = rng.uniform(40, 130, rows)
    appearance = (rng.uniform(0, 1, rows) < 0.3 + 0.6 * minutes / 90).astype("int64")
    conditional_minutes = np.clip(minutes + rng.normal(0, 10, rows), 1, 90)
    return pd.DataFrame(
        {
            "season": [seasons[0]] * (rows // 2) + [seasons[1]] * (rows - rows // 2),
            "minutes_last_3": minutes,
            "price_tenths": price,
            "fixture_count": np.where(rng.uniform(0, 1, rows) < double_share, 2, 1),
            "appearance_target": appearance,
            "minutes_target": np.where(appearance == 1, conditional_minutes, np.nan),
            "points_target": np.where(appearance == 1, rng.poisson(3, rows), np.nan),
        }
    )


def test_the_regime_labels_are_the_declared_cross_and_refuse_a_blank_row() -> None:
    frame = pd.DataFrame(
        {
            "season": ["2024-25", "2024-25", "2025-26", "2026-27"],
            "fixture_count": [1, 2, 1, 3],
        }
    )
    assert list(regime_labels(frame)) == [
        SINGLE_PRE_DEFCON_REGIME,
        DOUBLE_PRE_DEFCON_REGIME,
        SINGLE_DEFCON_REGIME,
        DOUBLE_DEFCON_REGIME,
    ]
    assert set(regime_labels(frame)) <= set(REGIME_LABELS)
    with pytest.raises(PredictionConfigurationError, match="blank"):
        regime_labels(frame.assign(fixture_count=[0, 1, 1, 1]))
    with pytest.raises(PredictionConfigurationError):
        regime_labels(frame.drop(columns=["season"]))


def test_the_gate_design_carries_the_three_regime_terms_and_refuses_a_future_row() -> None:
    frame = _training(rows=40)
    design = regime_design(frame, FEATURES, target_season=TARGET)
    assert list(design.columns) == [*FEATURES, *REGIME_GATE_TERMS]
    assert set(design["regime_season_age"]) == {0.0, 1.0}
    assert (design["regime_defcon_era"] == (frame["season"] == TARGET)).all()
    assert (design["regime_double_fixture"] == (frame["fixture_count"] >= 2)).all()
    with pytest.raises(PredictionConfigurationError, match="leak"):
        regime_design(frame, FEATURES, target_season="2024-25")


def test_the_candidate_carries_its_own_version_and_needs_the_target_season() -> None:
    fitted = fit_component_models(
        _training(), feature_columns=FEATURES, config=SMALL, target_season=TARGET
    )
    assert fitted is not None
    assert fitted.model_version == REGIME_MODEL_VERSION
    assert fitted.estimator == REGIME_ESTIMATOR
    assert fitted.weighting == EQUAL_WEIGHTING
    assert fitted.target_season == TARGET
    assert isinstance(fitted.appearance, RegimeMixture)
    summary = regime_expert_summary(fitted)
    assert set(summary) == set(REGIME_LABELS)
    assert all(entry["conditional_rows"] >= 10 for entry in summary.values())
    with pytest.raises(PredictionConfigurationError, match="target season"):
        fit_component_models(_training(), feature_columns=FEATURES, config=SMALL)
    with pytest.raises(PredictionConfigurationError, match="equal weighting"):
        fit_component_models(
            _training(),
            feature_columns=FEATURES,
            config=SMALL,
            weighting=SeasonAgeWeighting(target_season=TARGET),
            target_season=TARGET,
        )
    control = fit_component_models(_training(), feature_columns=FEATURES, config=LINEAR)
    assert control is not None
    assert control.model_version == COMPONENT_MODEL_VERSION
    assert control.target_season is None
    with pytest.raises(PredictionConfigurationError):
        regime_expert_summary(control)


def test_the_candidate_is_deterministic_and_keeps_the_control_bounds_and_routes() -> None:
    training = _training()
    scoring = _training(rows=80, seed=7)
    scoring.loc[0, "minutes_last_3"] = np.nan  # one incomplete row takes the fallback route
    scoring.loc[1, "fixture_count"] = 0  # one blank gameweek
    first = fit_component_models(
        training, feature_columns=FEATURES, config=SMALL, target_season=TARGET
    )
    second = fit_component_models(
        training, feature_columns=FEATURES, config=SMALL, target_season=TARGET
    )
    assert first is not None and second is not None
    left = predict_components(first, scoring, feature_columns=FEATURES)
    right = predict_components(second, scoring, feature_columns=FEATURES)
    assert_frame_equal(left, right)
    assert left.loc[0, "composition_route"] == "direct_control"
    assert pd.isna(left.loc[0, "appearance_probability"])
    assert left.loc[1, "composition_route"] == "component_model"
    assert float(left.loc[1, "appearance_probability"]) == 0.0
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
    weights = first.appearance.gate_weights(
        regime_design(scoring.loc[2:], FEATURES, target_season=TARGET)
    )
    assert weights.shape == (len(scoring) - 2, 4)
    assert np.allclose(weights.sum(axis=1), 1.0)
    # The scoring frame must carry its season for the regime terms.
    with pytest.raises(PredictionConfigurationError):
        predict_components(first, scoring.drop(columns=["season"]), feature_columns=FEATURES)


def test_one_regime_reproduces_the_linear_control_exactly() -> None:
    training = _training(seasons=("2024-25", "2024-25"), double_share=0.0)
    scoring = _training(rows=50, seed=3, seasons=("2024-25", "2024-25"), double_share=0.0)
    regime = fit_component_models(
        training, feature_columns=FEATURES, config=SMALL, target_season="2024-25"
    )
    linear = fit_component_models(training, feature_columns=FEATURES, config=LINEAR)
    assert regime is not None and linear is not None
    assert isinstance(regime.appearance, RegimeMixture)
    assert regime.appearance.gate is None
    assert list(regime_expert_summary(regime)) == [SINGLE_PRE_DEFCON_REGIME]
    mixed = predict_components(regime, scoring, feature_columns=FEATURES)
    control = predict_components(linear, scoring, feature_columns=FEATURES)
    for column in (
        "appearance_probability",
        "expected_minutes_if_appearance",
        "raw_expected_points_if_appearance",
    ):
        np.testing.assert_allclose(
            pd.to_numeric(mixed[column]).astype("float64"),
            pd.to_numeric(control[column]).astype("float64"),
        )


def test_an_absent_expert_hands_its_mass_to_the_present_ones() -> None:
    # Too few double-gameweek rows for an expert: the gate still sees the double label, but
    # every double row is scored by the single experts in the gate's renormalized shares.
    training = _training(double_share=0.02)
    regime = fit_component_models(
        training, feature_columns=FEATURES, config=SMALL, target_season=TARGET
    )
    assert regime is not None
    assert isinstance(regime.appearance, RegimeMixture)
    summary = regime_expert_summary(regime)
    assert DOUBLE_PRE_DEFCON_REGIME not in summary and DOUBLE_DEFCON_REGIME not in summary
    assert set(regime.appearance.gate_classes) >= {SINGLE_PRE_DEFCON_REGIME, SINGLE_DEFCON_REGIME}
    scoring = _training(rows=40, seed=5, double_share=1.0)
    design = regime_design(scoring, FEATURES, target_season=TARGET)
    weights = regime.appearance.gate_weights(design)
    assert weights.shape == (40, len(summary))
    assert np.allclose(weights.sum(axis=1), 1.0)
    predicted = predict_components(regime, scoring, feature_columns=FEATURES)
    assert (predicted["composition_route"] == "component_model").all()


def test_the_gate_routes_each_row_to_its_own_regime_expert() -> None:
    # Separable regimes: double-gameweek rows score eight points more. The gate reads the
    # double indicator, so it must put almost all of a row's mass on that row's expert, and
    # the mixture must follow that expert rather than the plain mean of the experts.
    seasons = ("2023-24", "2024-25")
    training = _training(rows=800, seasons=seasons, double_share=0.4)
    double_rows = training["fixture_count"] >= 2
    training.loc[double_rows, "points_target"] += 8.0
    regime = fit_component_models(
        training, feature_columns=FEATURES, config=SMALL, target_season="2024-25"
    )
    assert regime is not None
    assert isinstance(regime.points, RegimeMixture)
    labels = [expert.label for expert in regime.points.experts]
    assert labels == [SINGLE_PRE_DEFCON_REGIME, DOUBLE_PRE_DEFCON_REGIME]
    for share, own in ((0.0, 0), (1.0, 1)):
        scoring = _training(rows=60, seed=11, seasons=("2024-25", "2024-25"), double_share=share)
        design = regime_design(scoring, FEATURES, target_season="2024-25")
        weights = regime.points.gate_weights(design)
        assert weights[:, own].min() > 0.9
        experts = np.column_stack(
            [
                np.asarray(expert.points.predict(design.loc[:, list(FEATURES)]))
                for expert in regime.points.experts
            ]
        )
        mixed = regime.points.predict(design)
        np.testing.assert_allclose(mixed, experts[:, own], atol=0.1)
        assert np.abs(mixed - experts.mean(axis=1)).min() > 1.0


def test_the_v1_contract_refuses_the_regime_candidate(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["export_component_oof", "--estimator", REGIME_ESTIMATOR, "--seasons", f"{OLD},{NEW}"],
    )
    assert main() == 1
    assert "--development-scope v2" in capsys.readouterr().out


def test_the_v2_weighted_arm_refuses_the_regime_estimator(
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
            REGIME_ESTIMATOR,
        ],
    )
    assert main() == 1
    assert "equal weighting only" in capsys.readouterr().out


def test_the_v2_export_writes_the_regime_table_the_reader_and_the_comparison_accept(
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
        REGIME_ESTIMATOR,
        "--seasons",
        seasons,
    )
    table_path, _, manifest_path = candidate
    assert table_path.name == f"{DEVELOPMENT_OOF_CONTRACT_VERSION}_equal_regime.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["model_version"] == REGIME_MODEL_VERSION
    assert manifest["weighting"]["label"] == EQUAL_WEIGHTING
    assert manifest["estimator"]["name"] == REGIME_ESTIMATOR
    assert manifest["estimator"]["constants"]["regime_labels"] == list(REGIME_LABELS)
    assert manifest["estimator"]["constants"]["gate_terms"] == list(REGIME_GATE_TERMS)
    assert "--estimator regime" in manifest["reproduce"]
    assert all(record["estimator"] == REGIME_ESTIMATOR for record in manifest["folds"])
    handoff = read_phase_c_component_handoff(
        *candidate, development_contract=DEVELOPMENT_OOF_CONTRACT_VERSION
    )
    assert handoff.model_version == REGIME_MODEL_VERSION
    table = pd.read_csv(table_path)
    assert set(table["model_version"]) == {REGIME_MODEL_VERSION}
    modelled = table.loc[table["composition_route"] == "component_model"]
    assert not modelled.empty
    assert modelled["appearance_probability"].between(0.0, 1.0).all()
    assert (modelled["expected_points_if_appearance"] >= 0.0).all()

    artifact_dir = tmp_path / "pair"
    artifact_dir.mkdir()
    for paths in (control, candidate):
        for path in paths:
            (artifact_dir / path.name).write_bytes(path.read_bytes())
    arguments = ["--artifact-dir", str(artifact_dir), "--candidate-arm", "regime"]
    assert compare_main(arguments) == 0
    report_path = artifact_dir / "comparison_regime" / "comparison.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["candidate_arm"] == "regime"
    assert report["arms"]["candidate"]["model_version"] == REGIME_MODEL_VERSION
    assert report["verdict"]["verdict"] in {"candidate_preferred", "no_selection"}
    # The default arm still expects the weighted candidate and refuses the regime table.
    refused = ["--artifact-dir", str(artifact_dir), "--candidate", table_path.name[:-4]]
    assert compare_main(refused) == 1
