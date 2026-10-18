"""The gated-mixture candidate of the Phase C conditional components.

The candidate keeps the control's appearance estimator, rows, features, targets, routes and
bounds, and replaces each conditional ridge by a gated mixture of two ridge experts on a
declared regime label. These tests pin the contract of `docs/research/moe_mixture_prereg.md`:
its own model version, equal weighting only, the regime rules and the thin-regime refusal,
the gate-weighted mean, the distribution sidecar every v2 export writes, the comparison arm,
and the proper-scoring reading of the sidecars.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from scripts.compare_component_oof_development import main as compare_main
from scripts.export_component_oof import DEVELOPMENT_OOF_CONTRACT_VERSION, main
from scripts.score_component_distribution import main as score_main
from tests.unit.test_component_gradient_boosting import FEATURES, _training
from tests.unit.test_export_component_oof_v2 import LOCKED, NEW, OLD, THREE, _run_export

from squadopt.evaluation import EvaluationValidationError
from squadopt.experiments.component_distribution_scoring import (
    KEY_COLUMNS,
    declared_reading,
    log_density_sanity,
    paired_fold_reading,
    score_arms,
    score_rows,
    summarize,
)
from squadopt.prediction.component_models import (
    COMPONENT_MODEL_VERSION,
    DISTRIBUTION_COLUMNS,
    EQUAL_WEIGHTING,
    LINEAR_ESTIMATOR,
    MINUTES_FULL_THRESHOLD_PER_FIXTURE,
    MIXTURE_ESTIMATOR,
    MIXTURE_FAMILY,
    MIXTURE_MODEL_VERSION,
    POINTS_RETURN_THRESHOLD,
    SINGLE_GAUSSIAN_FAMILY,
    ComponentModelConfig,
    GatedMixtureRegressor,
    SeasonAgeWeighting,
    fit_component_models,
    predict_component_distribution,
    predict_components,
)
from squadopt.prediction.config import PredictionConfigurationError

SMALL = ComponentModelConfig(minimum_training_rows=10, estimator=MIXTURE_ESTIMATOR)
LINEAR = ComponentModelConfig(minimum_training_rows=10)


def test_the_candidate_carries_its_own_version_and_fits_two_experts_per_component() -> None:
    fitted = fit_component_models(_training(), feature_columns=FEATURES, config=SMALL)
    assert fitted is not None
    assert fitted.model_version == MIXTURE_MODEL_VERSION
    assert fitted.estimator == MIXTURE_ESTIMATOR
    assert fitted.weighting == EQUAL_WEIGHTING
    assert isinstance(fitted.minutes, GatedMixtureRegressor)
    assert isinstance(fitted.points, GatedMixtureRegressor)
    # The regime rules of the declaration, recounted on the fitted rows.
    training = _training()
    appeared = training.loc[training["appearance_target"] == 1]
    full = int(
        (
            appeared["minutes_target"]
            >= MINUTES_FULL_THRESHOLD_PER_FIXTURE * appeared["fixture_count"]
        ).sum()
    )
    returned = int((appeared["points_target"] >= POINTS_RETURN_THRESHOLD).sum())
    assert (fitted.minutes.high_rows, fitted.minutes.low_rows) == (full, len(appeared) - full)
    assert (fitted.points.high_rows, fitted.points.low_rows) == (
        returned,
        len(appeared) - returned,
    )
    assert fitted.minutes.low_scale >= 1.0 and fitted.points.low_scale >= 0.5
    # The linear control is untouched and now records its single Gaussian scale.
    control = fit_component_models(_training(), feature_columns=FEATURES, config=LINEAR)
    assert control is not None
    assert control.model_version == COMPONENT_MODEL_VERSION
    assert control.estimator == LINEAR_ESTIMATOR
    assert control.minutes_scale is not None and control.points_scale is not None


def test_the_candidate_refuses_season_weighting_and_thin_regimes() -> None:
    with pytest.raises(PredictionConfigurationError):
        fit_component_models(
            _training(),
            feature_columns=FEATURES,
            config=SMALL,
            weighting=SeasonAgeWeighting(target_season="2024-25"),
        )
    # Every appeared row in the return regime: the points gate has one class, so the fold is
    # refused rather than fitted on a constant.
    training = _training()
    training["points_target"] = np.where(training["appearance_target"] == 1, 9.0, np.nan)
    assert fit_component_models(training, feature_columns=FEATURES, config=SMALL) is None
    # A regime below max(2, minimum_training_rows // 4) rows is refused too.
    thin = _training()
    appeared = thin.index[thin["appearance_target"] == 1]
    thin.loc[appeared, "points_target"] = 1.0
    thin.loc[appeared[:1], "points_target"] = 8.0
    assert fit_component_models(thin, feature_columns=FEATURES, config=SMALL) is None


def test_the_expected_value_is_the_gate_weighted_mean_within_the_control_bounds() -> None:
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
    assert left.loc[1, "composition_route"] == "component_model"
    assert float(left.loc[1, "expected_minutes_if_appearance"]) == 0.0
    distribution = predict_component_distribution(first, scoring, feature_columns=FEATURES)
    assert list(distribution.columns) == list(DISTRIBUTION_COLUMNS)
    assert 0 not in distribution.index and 1 not in distribution.index
    assert (distribution["distribution_family"] == MIXTURE_FAMILY).all()
    modelled = left.loc[distribution.index]
    expected_points = (
        distribution["points_gate"] * distribution["points_mean_high"]
        + (1.0 - distribution["points_gate"]) * distribution["points_mean_low"]
    )
    raw = pd.to_numeric(modelled["raw_expected_points_if_appearance"]).astype("float64")
    assert np.allclose(raw.to_numpy(), expected_points.to_numpy())
    expected_minutes = (
        distribution["minutes_gate"] * distribution["minutes_mean_high"]
        + (1.0 - distribution["minutes_gate"]) * distribution["minutes_mean_low"]
    )
    ceiling = scoring.loc[distribution.index, "fixture_count"].astype("float64") * 90.0
    minutes = pd.to_numeric(modelled["expected_minutes_if_appearance"]).astype("float64")
    assert np.allclose(minutes.to_numpy(), np.clip(expected_minutes, 0.0, ceiling).to_numpy())
    assert distribution["points_gate"].between(0.0, 1.0).all()
    points = pd.to_numeric(modelled["expected_points_if_appearance"]).astype("float64")
    assert (points >= 0.0).all()
    probability = pd.to_numeric(modelled["appearance_probability"]).astype("float64")
    assert probability.between(0.0, 1.0).all()
    # The linear arm's distribution is a single Gaussian: gate 0, high slots missing.
    control = fit_component_models(training, feature_columns=FEATURES, config=LINEAR)
    single = predict_component_distribution(control, scoring, feature_columns=FEATURES)
    assert (single["distribution_family"] == SINGLE_GAUSSIAN_FAMILY).all()
    assert (single["points_gate"] == 0.0).all()
    assert single["points_mean_high"].isna().all() and single["points_scale_high"].isna().all()
    assert np.allclose(
        single["points_mean_low"].to_numpy(),
        pd.to_numeric(
            predict_components(control, scoring, feature_columns=FEATURES).loc[
                single.index, "raw_expected_points_if_appearance"
            ]
        )
        .astype("float64")
        .to_numpy(),
    )
    # The boosted arms declare no distribution.
    boosted = fit_component_models(
        training,
        feature_columns=FEATURES,
        config=ComponentModelConfig(
            minimum_training_rows=10, estimator="gradient_boosting", boosting_iterations=5
        ),
    )
    assert predict_component_distribution(boosted, scoring, feature_columns=FEATURES).empty
    assert predict_component_distribution(None, scoring, feature_columns=FEATURES).empty


def test_the_v1_contract_and_the_weighted_arm_refuse_the_mixture(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["export_component_oof", "--estimator", MIXTURE_ESTIMATOR, "--seasons", f"{OLD},{NEW}"],
    )
    assert main() == 1
    assert "--development-scope v2" in capsys.readouterr().out
    monkeypatch.setattr(
        "sys.argv",
        [
            "export_component_oof",
            "--development-scope",
            "v2",
            "--season-weighting",
            "season_half_life",
            "--estimator",
            MIXTURE_ESTIMATOR,
        ],
    )
    assert main() == 1
    assert "equal weighting only" in capsys.readouterr().out


def test_the_v2_export_writes_the_sidecar_the_comparison_and_the_scoring_accept(
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
        MIXTURE_ESTIMATOR,
        "--seasons",
        seasons,
    )
    table_path, _, manifest_path = candidate
    assert table_path.name == f"{DEVELOPMENT_OOF_CONTRACT_VERSION}_equal_mixture.csv"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["model_version"] == MIXTURE_MODEL_VERSION
    assert manifest["estimator"]["name"] == MIXTURE_ESTIMATOR
    assert manifest["estimator"]["constants"]["points_return_threshold"] == 4.0
    assert manifest["estimator"]["constants"]["minutes_full_threshold_per_fixture"] == 60.0
    assert "--estimator mixture" in manifest["reproduce"]
    assert all(record["estimator"] == MIXTURE_ESTIMATOR for record in manifest["folds"])
    sidecar = manifest["estimator"]["distribution_sidecar"]
    assert sidecar["family"] == MIXTURE_FAMILY
    sidecar_path = table_path.with_name(sidecar["path"])
    assert sidecar_path.name == f"{DEVELOPMENT_OOF_CONTRACT_VERSION}_equal_mixture.distribution.csv"
    rows = pd.read_csv(sidecar_path)
    assert list(rows.columns) == [*KEY_COLUMNS, *DISTRIBUTION_COLUMNS]
    assert len(rows) == sidecar["row_count"]
    table = pd.read_csv(table_path)
    modelled = table.loc[
        (table["composition_route"] == "component_model") & (table["fixture_count"] > 0)
    ]
    assert len(rows) == len(modelled)
    control_manifest = json.loads(control[2].read_text(encoding="utf-8"))
    assert control_manifest["estimator"]["name"] == LINEAR_ESTIMATOR
    assert control_manifest["estimator"]["distribution_sidecar"]["family"] == SINGLE_GAUSSIAN_FAMILY

    artifact_dir = tmp_path / "pair"
    artifact_dir.mkdir()
    for paths in (control, candidate):
        for path in paths:
            (artifact_dir / path.name).write_bytes(path.read_bytes())
        first_table = paths[0]
        sidecar_name = first_table.name[:-4] + ".distribution.csv"
        (artifact_dir / sidecar_name).write_bytes(first_table.with_name(sidecar_name).read_bytes())
    arguments = ["--artifact-dir", str(artifact_dir), "--candidate-arm", "mixture"]
    assert compare_main(arguments) == 0
    report = json.loads(
        (artifact_dir / "comparison_mixture" / "comparison.json").read_text(encoding="utf-8")
    )
    assert report["candidate_arm"] == "mixture"
    assert report["arms"]["candidate"]["model_version"] == MIXTURE_MODEL_VERSION
    assert report["primary_season"]["season"] == LOCKED
    assert report["verdict"]["verdict"] in {"candidate_preferred", "no_selection"}

    assert score_main(arguments) == 0
    scoring = json.loads(
        (artifact_dir / "comparison_mixture" / "distribution_scoring.json").read_text(
            encoding="utf-8"
        )
    )
    assert scoring["candidate_arm"] == "mixture"
    assert scoring["enters_points_mae_rule"] is False
    for component in ("points", "minutes"):
        block = scoring["components"][component]
        assert block["reading"] in {"sharper", "worse", "undecided"}
        assert block["primary_season"]["season"] == LOCKED
        assert block["pooled"]["control"]["rows"] == scoring["rows"]
        assert 0.0 <= block["pooled"]["candidate"]["mean_pit"] <= 1.0
    readout = (artifact_dir / "comparison_mixture" / "distribution_scoring.md").read_text(
        encoding="utf-8"
    )
    assert "points given an appearance" in readout
    # A sidecar that does not match its manifest digest is refused.
    tampered = artifact_dir / f"{DEVELOPMENT_OOF_CONTRACT_VERSION}_equal_mixture.distribution.csv"
    tampered.write_text(tampered.read_text(encoding="utf-8").replace("0.5", "0.6", 1), "utf-8")
    assert score_main(arguments) == 1


def _scored_rows(seed: int, *, family: str) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = 40
    frame = pd.DataFrame(
        {
            "season": ["2024-25"] * (rows // 2) + ["2025-26"] * (rows // 2),
            "target_gameweek": [2 + index % 4 for index in range(rows)],
            "player_id": list(range(rows)),
            "points_target": rng.integers(0, 10, rows).astype("float64"),
            "minutes_target": rng.integers(1, 91, rows).astype("float64"),
            "distribution_family": family,
            "minutes_gate": 0.5,
            "minutes_mean_low": 20.0,
            "minutes_mean_high": 85.0,
            "minutes_scale_low": 10.0,
            "minutes_scale_high": 5.0,
            "points_gate": 0.3,
            "points_mean_low": 2.0,
            "points_mean_high": 6.0,
            "points_scale_low": 1.0,
            "points_scale_high": 2.5,
        }
    )
    frame["fold_id"] = frame["season"] + "-gw" + frame["target_gameweek"].map("{:02d}".format)
    return frame


def test_the_scoring_is_a_discretised_mixture_and_the_reading_follows_the_declaration() -> None:
    rows = _scored_rows(0, family=MIXTURE_FAMILY)
    scored = score_rows(rows, component="points")
    assert list(scored.columns) == [*KEY_COLUMNS, "log_score", "pit"]
    # One row by hand: the mixture probability of the integer is the gated sum of the two
    # discretised Gaussians.
    y = float(rows.loc[0, "points_target"])
    low = log_density_sanity(y, 2.0, 1.0)
    high = log_density_sanity(y, 6.0, 2.5)
    assert math.isclose(float(scored.loc[0, "log_score"]), math.log(0.3 * high + 0.7 * low))
    assert scored["pit"].between(0.0, 1.0).all()
    # A single Gaussian with gate 0 ignores the missing high slot.
    single = rows.copy()
    single["points_gate"] = 0.0
    single["points_mean_high"] = np.nan
    single["points_scale_high"] = np.nan
    single_scored = score_rows(single, component="points")
    assert math.isclose(float(single_scored.loc[0, "log_score"]), math.log(low))
    summary = summarize(scored)
    assert summary.rows == len(rows)
    # Paired reading: a candidate that is the control shifted toward the realized values
    # scores higher on every fold, and the declaration reads it as sharper.
    better = rows.copy()
    better["points_mean_low"] = rows["points_target"]
    better["points_scale_low"] = 0.8
    better["points_gate"] = 0.0
    better["points_mean_high"] = np.nan
    better["points_scale_high"] = np.nan
    control_scores = score_rows(rows, component="points")
    better_scores = score_rows(better, component="points")
    primary = paired_fold_reading(
        control_scores, better_scores, season="2025-26", candidate_id="test_primary"
    )
    control_era = paired_fold_reading(
        control_scores, better_scores, season="2024-25", candidate_id="test_era"
    )
    assert primary.wins == primary.folds and primary.interval_low > 0
    assert declared_reading(primary, control_era) == "sharper"
    assert declared_reading(control_era, primary) == "sharper"
    worse = paired_fold_reading(
        better_scores, control_scores, season="2025-26", candidate_id="test_worse"
    )
    assert declared_reading(worse, control_era) == "worse"
    report = score_arms(
        rows, better, primary_season="2025-26", control_era_season="2024-25", candidate_id="t"
    )
    assert report["components"]["points"]["reading"] == "sharper"
    assert report["rows"] == len(rows)
    # Two arms on different rows are not one paired reading.
    with pytest.raises(EvaluationValidationError):
        score_arms(
            rows,
            better.iloc[1:],
            primary_season="2025-26",
            control_era_season="2024-25",
            candidate_id="t",
        )
