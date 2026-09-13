"""Descriptive precision diagnostics for paired, pre-decision fold covariates."""

from collections.abc import Mapping, Sequence
from statistics import NormalDist
from typing import Any

import numpy as np


def _vector(values: Sequence[float], label: str) -> np.ndarray:
    if any(isinstance(value, bool) for value in values):
        raise ValueError(f"{label} cannot contain boolean measurements.")
    result = np.asarray(values, dtype=float)
    if result.ndim != 1 or len(result) < 3 or not np.isfinite(result).all():
        raise ValueError(f"{label} needs at least three finite observations.")
    return result


def _precision(values: np.ndarray) -> dict[str, float | int]:
    sd = float(np.std(values, ddof=1))
    se = sd / len(values) ** 0.5
    normal = NormalDist()
    return {
        "folds": len(values),
        "mean": float(np.mean(values)),
        "standard_deviation": sd,
        "iid_standard_error": se,
        "iid_90_interval_half_width": normal.inv_cdf(0.95) * se,
        "iid_mde_alpha_0_05_power_0_8": (normal.inv_cdf(0.975) + normal.inv_cdf(0.8)) * se,
    }


def compare_precision(
    differences: Sequence[float],
    covariates: Mapping[str, Sequence[float]],
    *,
    min_history: int = 24,
) -> dict[str, Any]:
    """Report row residualization separately from precision of the mean estimator.

    Sample-centering makes mean(d - theta * (x - mean(x))) exactly mean(d).
    The smaller residual standard error is conditional, not an unconditional gain.
    Forward fits are a diagnostic on held-out folds, never a promotion statistic.
    """
    if isinstance(min_history, bool) or not isinstance(min_history, int) or min_history < 3:
        raise ValueError("min_history must be at least three.")
    difference = _vector(differences, "differences")
    baseline = _precision(difference)
    results: list[dict[str, Any]] = []
    for name, values in covariates.items():
        covariate = _vector(values, name)
        if len(covariate) != len(difference):
            raise ValueError("Covariates must use exactly the paired fold population.")
        centered = covariate - covariate.mean()
        denominator = float(centered @ centered)
        if denominator == 0 or float(np.var(difference)) == 0:
            results.append({"name": name, "status": "constant", "correlation": None})
            continue
        theta = float(centered @ (difference - difference.mean()) / denominator)
        correlation = float(np.corrcoef(difference, covariate)[0, 1])
        residual = difference - theta * centered
        forward: list[float] = []
        matched: list[float] = []
        for index in range(min_history, len(difference)):
            x = covariate[:index]
            x_centered = x - x.mean()
            variance = float(x_centered @ x_centered)
            if variance == 0:
                continue
            coefficient = float(
                x_centered @ (difference[:index] - difference[:index].mean()) / variance
            )
            forward.append(float(difference[index] - coefficient * (covariate[index] - x.mean())))
            matched.append(float(difference[index]))
        results.append(
            {
                "name": name,
                "status": "measured",
                "correlation": correlation,
                "theta": theta,
                "sample_covariate_mean": float(covariate.mean()),
                "residual_variance_ratio": float(
                    np.var(residual, ddof=1) / np.var(difference, ddof=1)
                ),
                "conditional_residual_precision": _precision(residual),
                "unconditional_mean_precision": baseline,
                "forward_diagnostic": {
                    "minimum_training_folds": min_history,
                    "raw_matched": _precision(np.asarray(matched)) if len(matched) >= 3 else None,
                    "adjusted": _precision(np.asarray(forward)) if len(forward) >= 3 else None,
                    "interpretation": (
                        "historically fitted center; descriptive, not an unbiased precision claim"
                    ),
                },
            }
        )
    measured = [row for row in results if row["status"] == "measured"]
    best = max(measured, key=lambda row: abs(row["correlation"]), default=None)
    return {
        "raw": baseline,
        "covariates": results,
        "largest_absolute_correlation": best["name"] if best else None,
        "validated_unconditional_precision_gain": False,
        "centering_policy": "same-sample mean; adjusted mean estimator is algebraically unchanged",
        "assumptions": (
            "IID normal approximation only; overlapping squads and weeks can violate independence"
        ),
    }
