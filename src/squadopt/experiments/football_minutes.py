"""Research-only sequential minute categories with unchanged causal features."""

from __future__ import annotations

from copy import copy
from typing import Any

import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin  # type: ignore[import-untyped]
from sklearn.linear_model import LogisticRegression  # type: ignore[import-untyped]
from sklearn.pipeline import make_pipeline  # type: ignore[import-untyped]

from squadopt.prediction.football import Array, FixtureFootballModel, _fit, _matrix, _pipeline
from squadopt.prediction.football_features import FEATURES

MODEL_ID = "football_sequential_minutes_dev_v1"


class SequentialMinutes(ClassifierMixin, BaseEstimator):  # type: ignore[misc]
    """Factor appearance, 60-minute eligibility and full-match exposure separately."""

    def fit(self, x: Array, y: Array) -> SequentialMinutes:
        y = np.asarray(y)
        if len(x) != len(y) or not len(y) or not np.isin(y, range(4)).all():
            raise ValueError("Minute training requires aligned labels in 0..3.")
        if not np.isfinite(x).all():
            raise ValueError("Minute features must be finite.")
        self.classes_ = np.arange(4)
        self.n_features_in_ = x.shape[1]
        self.stages_: list[Any] = []
        for stage in range(3):
            mask = y >= stage
            label = (y[mask] > stage).astype(int)
            if not len(label) or len(np.unique(label)) < 2:
                self.stages_.append(float(label.mean()) if len(label) else 0.0)
            else:
                self.stages_.append(
                    _fit(
                        _pipeline(LogisticRegression(C=1, max_iter=1000, random_state=0)),
                        x[mask],
                        label,
                    )
                )
        return self

    def predict_proba(self, x: Array) -> Array:
        if not np.isfinite(x).all() or x.shape[1] != self.n_features_in_:
            raise ValueError("Minute prediction features are invalid.")
        probabilities = np.zeros((len(x), 4))
        remaining = np.ones(len(x))
        for stage, fitted in enumerate(self.stages_):
            conditional = (
                np.full(len(x), fitted)
                if isinstance(fitted, float)
                else np.asarray(fitted.predict_proba(x)[:, 1], float)
            )
            probabilities[:, stage] = remaining * (1 - conditional)
            remaining *= conditional
        probabilities[:, 3] = remaining
        return probabilities


class SequentialMinuteForecast:
    """Copy a fitted control, replacing only minutes and always naming the new arm."""

    model_version = MODEL_ID

    def __init__(self, control: FixtureFootballModel, train: pd.DataFrame):
        if not (train.kickoff + pd.Timedelta(hours=3) < control.cutoff).all():
            raise ValueError("Minute labels are unavailable at the control cutoff.")
        self._candidate = copy(control)
        self._candidate.minutes = make_pipeline(SequentialMinutes()).fit(
            _matrix(train, FEATURES), train.m_bin.to_numpy()
        )

    def predict(self, target: pd.DataFrame) -> pd.DataFrame:
        result = self._candidate.predict(target)
        result["model_version"] = MODEL_ID
        return result
