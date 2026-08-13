"""Deterministic Ridge reference model for one-gameweek point projections.

This module owns only model fitting and inference on an already leakage-safe
feature table. Chronological slicing and optimizer integration remain in the
backtest layer, so the fitted model never decides which rows are historical.
"""

import hashlib
import json
import math
from dataclasses import dataclass
from numbers import Integral, Real
from typing import Final

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge  # type: ignore[import-untyped]

from squadopt.data.schema import POSITIONS
from squadopt.features import (
    PRIOR_MINUTES_COLUMN,
    PRIOR_RATE_COLUMN,
    FeatureConfigurationError,
    per_90_feature_name,
    rolling_feature_name,
)
from squadopt.prediction.config import PredictionConfigurationError
from squadopt.prediction.factors import FormWindowMapping

RIDGE_MODEL_NAME: Final = "squadopt-ridge-reference"
RIDGE_MODEL_VERSION: Final = "ridge-reference-v1"
RIDGE_FEATURE_CONTRACT_VERSION: Final = "ridge-features-v1"


@dataclass(frozen=True, slots=True)
class RidgeProjectionConfig:
    """Fixed controls for the open-source learned projection reference."""

    form_window: int = 5
    alpha: float = 10.0
    min_training_rows: int = 100

    def __post_init__(self) -> None:
        try:
            mapping = FormWindowMapping(form_window=self.form_window)
        except FeatureConfigurationError as error:
            raise PredictionConfigurationError(str(error)) from error
        if isinstance(self.alpha, bool) or not isinstance(self.alpha, Real):
            raise PredictionConfigurationError("alpha must be a finite positive number.")
        alpha = float(self.alpha)
        if not math.isfinite(alpha) or alpha <= 0.0:
            raise PredictionConfigurationError("alpha must be a finite positive number.")
        if isinstance(self.min_training_rows, bool) or not isinstance(
            self.min_training_rows, Integral
        ):
            raise PredictionConfigurationError("min_training_rows must be an integer.")
        minimum = int(self.min_training_rows)
        if minimum < 2:
            raise PredictionConfigurationError("min_training_rows must be at least 2.")
        object.__setattr__(self, "form_window", mapping.form_window)
        object.__setattr__(self, "alpha", alpha)
        object.__setattr__(self, "min_training_rows", minimum)

    @property
    def feature_names(self) -> tuple[str, ...]:
        """Return the stable model-matrix column order."""

        window = self.form_window
        return (
            "price_tenths",
            rolling_feature_name("minutes", window),
            rolling_feature_name("total_points", window),
            per_90_feature_name(window),
            PRIOR_MINUTES_COLUMN,
            PRIOR_RATE_COLUMN,
            *(f"position_{position}" for position in POSITIONS),
        )


@dataclass(frozen=True, slots=True)
class FittedRidgePredictor:
    """Portable fitted Ridge state without exposing a scikit-learn object."""

    config: RidgeProjectionConfig
    feature_names: tuple[str, ...]
    imputation_values: tuple[float, ...]
    centers: tuple[float, ...]
    scales: tuple[float, ...]
    coefficients: tuple[float, ...]
    intercept: float
    training_rows: int
    training_data_fingerprint: str
    model_fingerprint: str

    def __post_init__(self) -> None:
        if not isinstance(self.config, RidgeProjectionConfig):
            raise PredictionConfigurationError("config must be a RidgeProjectionConfig.")
        expected = len(self.feature_names)
        vectors = (
            self.imputation_values,
            self.centers,
            self.scales,
            self.coefficients,
        )
        if self.feature_names != self.config.feature_names:
            raise PredictionConfigurationError("feature_names do not match the Ridge config.")
        if any(len(vector) != expected for vector in vectors):
            raise PredictionConfigurationError("Fitted Ridge vectors must align with features.")
        values = [value for vector in vectors for value in vector]
        values.append(self.intercept)
        if any(not math.isfinite(float(value)) for value in values):
            raise PredictionConfigurationError("Fitted Ridge state must contain finite numbers.")
        if any(float(value) <= 0.0 for value in self.scales):
            raise PredictionConfigurationError("Fitted Ridge scales must be positive.")
        if self.training_rows < self.config.min_training_rows:
            raise PredictionConfigurationError("Fitted Ridge state has too few training rows.")
        for name, digest in (
            ("training_data_fingerprint", self.training_data_fingerprint),
            ("model_fingerprint", self.model_fingerprint),
        ):
            if len(digest) != 64 or any(
                character not in "0123456789abcdef" for character in digest
            ):
                raise PredictionConfigurationError(f"{name} must be a lowercase SHA-256 digest.")
        expected_model_fingerprint = _model_fingerprint(
            self.config,
            imputation=np.asarray(self.imputation_values, dtype="float64"),
            centers=np.asarray(self.centers, dtype="float64"),
            scales=np.asarray(self.scales, dtype="float64"),
            coefficients=np.asarray(self.coefficients, dtype="float64"),
            intercept=self.intercept,
            training_data_fingerprint=self.training_data_fingerprint,
        )
        if self.model_fingerprint != expected_model_fingerprint:
            raise PredictionConfigurationError(
                "model_fingerprint does not match the fitted Ridge state."
            )


def _numeric_feature_names(config: RidgeProjectionConfig) -> tuple[str, ...]:
    return config.feature_names[:6]


def _validate_feature_frame(features: object, config: RidgeProjectionConfig) -> pd.DataFrame:
    if not isinstance(features, pd.DataFrame):
        raise PredictionConfigurationError("Ridge features must be a pandas DataFrame.")
    duplicates = features.columns[features.columns.duplicated()].tolist()
    if duplicates:
        raise PredictionConfigurationError(
            f"Ridge features contain duplicate columns: {duplicates!r}."
        )
    required = ("position", *_numeric_feature_names(config))
    missing = [column for column in required if column not in features.columns]
    if missing:
        raise PredictionConfigurationError(f"Ridge features are missing columns: {missing!r}.")
    frame = features.copy(deep=True)
    invalid_positions = sorted(
        {str(value) for value in frame["position"].dropna().tolist() if value not in POSITIONS}
    )
    if bool(frame["position"].isna().any()) or invalid_positions:
        raise PredictionConfigurationError(
            "Ridge feature positions must be in "
            f"{list(POSITIONS)!r}; invalid={invalid_positions!r}."
        )
    for column in _numeric_feature_names(config):
        try:
            converted = pd.to_numeric(frame[column], errors="raise").astype("float64")
        except (TypeError, ValueError) as error:
            raise PredictionConfigurationError(
                f"Ridge feature {column!r} must be numeric or missing."
            ) from error
        finite_or_missing = converted.isna() | np.isfinite(converted)
        if not bool(finite_or_missing.all()):
            raise PredictionConfigurationError(
                f"Ridge feature {column!r} must not contain infinite values."
            )
        frame[column] = converted
    return frame


def _raw_matrix(features: pd.DataFrame, config: RidgeProjectionConfig) -> np.ndarray:
    numeric = features.loc[:, list(_numeric_feature_names(config))].to_numpy(dtype="float64")
    position = np.column_stack(
        [(features["position"] == label).to_numpy(dtype="float64") for label in POSITIONS]
    )
    return np.column_stack((numeric, position))


def _training_fingerprint(features: pd.DataFrame, config: RidgeProjectionConfig) -> str:
    identity = [column for column in ("season", "gameweek", "player_id") if column in features]
    columns = [*identity, "position", *_numeric_feature_names(config), "total_points"]
    selected = features.loc[:, columns]
    if identity:
        selected = selected.sort_values(identity, kind="stable").reset_index(drop=True)
    row_hashes = pd.util.hash_pandas_object(selected, index=False, categorize=True)
    payload = {
        "contract_version": RIDGE_FEATURE_CONTRACT_VERSION,
        "form_window": config.form_window,
        "alpha": config.alpha,
        "feature_names": config.feature_names,
        "rows": len(selected),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    )
    digest.update(row_hashes.to_numpy(dtype="uint64").tobytes())
    return digest.hexdigest()


def _model_fingerprint(
    config: RidgeProjectionConfig,
    *,
    imputation: np.ndarray,
    centers: np.ndarray,
    scales: np.ndarray,
    coefficients: np.ndarray,
    intercept: float,
    training_data_fingerprint: str,
) -> str:
    payload = {
        "model_name": RIDGE_MODEL_NAME,
        "model_version": RIDGE_MODEL_VERSION,
        "feature_contract_version": RIDGE_FEATURE_CONTRACT_VERSION,
        "form_window": config.form_window,
        "alpha": config.alpha,
        "training_data_fingerprint": training_data_fingerprint,
        "imputation": [float(value).hex() for value in imputation],
        "centers": [float(value).hex() for value in centers],
        "scales": [float(value).hex() for value in scales],
        "coefficients": [float(value).hex() for value in coefficients],
        "intercept": float(intercept).hex(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fit_ridge_predictor(
    training_features: pd.DataFrame,
    config: RidgeProjectionConfig | None = None,
) -> FittedRidgePredictor:
    """Fit deterministic standardized Ridge on caller-selected historical rows."""

    settings = RidgeProjectionConfig() if config is None else config
    if not isinstance(settings, RidgeProjectionConfig):
        raise PredictionConfigurationError("config must be a RidgeProjectionConfig.")
    frame = _validate_feature_frame(training_features, settings)
    if "total_points" not in frame.columns:
        raise PredictionConfigurationError("Ridge training features require total_points labels.")
    if len(frame) < settings.min_training_rows:
        raise PredictionConfigurationError(
            f"Ridge training needs at least {settings.min_training_rows} rows; got {len(frame)}."
        )
    try:
        target = pd.to_numeric(frame["total_points"], errors="raise").to_numpy(dtype="float64")
    except (TypeError, ValueError) as error:
        raise PredictionConfigurationError("Ridge total_points labels must be numeric.") from error
    if not bool(np.isfinite(target).all()):
        raise PredictionConfigurationError("Ridge total_points labels must be finite.")

    raw = _raw_matrix(frame, settings)
    imputation = np.zeros(raw.shape[1], dtype="float64")
    for index in range(raw.shape[1]):
        observed = raw[np.isfinite(raw[:, index]), index]
        imputation[index] = float(np.median(observed)) if observed.size else 0.0
    imputed = np.where(np.isnan(raw), imputation, raw)
    centers = imputed.mean(axis=0)
    scales = imputed.std(axis=0)
    scales[scales == 0.0] = 1.0
    standardized = (imputed - centers) / scales

    estimator = Ridge(
        alpha=settings.alpha,
        fit_intercept=True,
        copy_X=False,
        solver="cholesky",
    )
    estimator.fit(standardized, target)
    coefficients = np.asarray(estimator.coef_, dtype="float64")
    intercept = float(estimator.intercept_)
    training_fingerprint = _training_fingerprint(frame, settings)
    model_fingerprint = _model_fingerprint(
        settings,
        imputation=imputation,
        centers=centers,
        scales=scales,
        coefficients=coefficients,
        intercept=intercept,
        training_data_fingerprint=training_fingerprint,
    )
    return FittedRidgePredictor(
        config=settings,
        feature_names=settings.feature_names,
        imputation_values=tuple(float(value) for value in imputation),
        centers=tuple(float(value) for value in centers),
        scales=tuple(float(value) for value in scales),
        coefficients=tuple(float(value) for value in coefficients),
        intercept=intercept,
        training_rows=len(frame),
        training_data_fingerprint=training_fingerprint,
        model_fingerprint=model_fingerprint,
    )


def _raw_predictions(features: pd.DataFrame, model: FittedRidgePredictor) -> np.ndarray:
    frame = _validate_feature_frame(features, model.config)
    raw = _raw_matrix(frame, model.config)
    imputed = np.where(np.isnan(raw), np.asarray(model.imputation_values), raw)
    standardized = (imputed - np.asarray(model.centers)) / np.asarray(model.scales)
    predicted = standardized @ np.asarray(model.coefficients) + model.intercept
    return np.asarray(predicted, dtype="float64")


def predict_ridge_expected_points(
    features: pd.DataFrame,
    model: FittedRidgePredictor,
) -> pd.Series:
    """Predict non-negative expected points without mutating the feature table."""

    if not isinstance(model, FittedRidgePredictor):
        raise PredictionConfigurationError("model must be a FittedRidgePredictor.")
    predicted = np.maximum(_raw_predictions(features, model), 0.0)
    return pd.Series(predicted, index=features.index, name="expected_points", dtype="float64")
