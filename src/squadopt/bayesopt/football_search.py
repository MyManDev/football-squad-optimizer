"""Equal-budget continuous-parameter research benchmark with optional BoTorch.

Uses a common finite Sobol pool and four common initial observations. This is
deterministic LogEI, not a claim that correlated validation folds are noisy IID draws.
No product module imports this optional research dependency.
"""

from __future__ import annotations

import importlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.special import ndtr
from scipy.stats import qmc
from sklearn.gaussian_process import GaussianProcessRegressor  # type: ignore[import-untyped]
from sklearn.gaussian_process.kernels import (  # type: ignore[import-untyped]
    ConstantKernel,
    Matern,
)

BOUNDS = np.array([[30.0, 4.0, 3.0], [180.0, 24.0, 30.0]])
PARAMETERS = ("half_life_days", "prior", "role_prior")


def decode(point: np.ndarray[Any, Any]) -> dict[str, float]:
    if point.shape != (3,) or not np.isfinite(point).all() or ((point < 0) | (point > 1)).any():
        raise ValueError("Football search requires three normalized coordinates.")
    return dict(
        zip(PARAMETERS, map(float, BOUNDS[0] + point * (BOUNDS[1] - BOUNDS[0])), strict=True)
    )


def _botorch_choice(
    x: np.ndarray[Any, Any], y: np.ndarray[Any, Any], pool: np.ndarray[Any, Any]
) -> int:
    try:
        torch = importlib.import_module("torch")
        gp = importlib.import_module("botorch.models").SingleTaskGP
        fit = importlib.import_module("botorch.fit").fit_gpytorch_mll
        log_ei = importlib.import_module("botorch.acquisition.analytic").LogExpectedImprovement
        mll_class = importlib.import_module("gpytorch.mlls").ExactMarginalLogLikelihood
    except ImportError as error:
        raise RuntimeError(
            "Install the research-bo extra in an isolated research environment."
        ) from error

    def tensor(a: np.ndarray[Any, Any]) -> Any:
        return torch.as_tensor(a, dtype=torch.double, device="cpu")

    # Standardize the minimized loss into a maximized objective, with numerical jitter only.
    values = (-(y - y.mean()) / max(float(y.std()), 1e-12))[:, None]
    model = gp(tensor(x), tensor(values), train_Yvar=torch.full_like(tensor(values), 1e-6))
    fit(mll_class(model.likelihood, model), optimizer_kwargs={"options": {"maxiter": 75}})
    acquisition = log_ei(model, best_f=float(values.max()))
    with torch.no_grad():
        scores = acquisition(tensor(pool)[:, None, :]).cpu().numpy()
    if not np.isfinite(scores).all():
        raise ValueError("BoTorch returned nonfinite acquisition scores.")
    return int(np.argmax(scores))


def _sklearn_choice(
    x: np.ndarray[Any, Any], y: np.ndarray[Any, Any], pool: np.ndarray[Any, Any]
) -> int:
    model = GaussianProcessRegressor(
        kernel=ConstantKernel(1.0, constant_value_bounds="fixed")
        * Matern(length_scale=1.0, length_scale_bounds="fixed", nu=2.5),
        alpha=1e-6,
        normalize_y=True,
        optimizer=None,
    ).fit(x, y)
    mean, std = model.predict(pool, return_std=True)
    delta = y.min() - mean
    z = np.divide(delta, std, out=np.zeros_like(delta), where=std > 0)
    ei = delta * ndtr(z) + std * np.exp(-(z**2) / 2) / np.sqrt(2 * np.pi)
    ei[std <= 0] = np.maximum(delta[std <= 0], 0)
    return int(np.argmax(ei))


@dataclass(frozen=True)
class SearchResult:
    method: str
    seed: int
    parameters: dict[str, float]
    loss: float
    trials: tuple[dict[str, Any], ...]


def search(
    evaluator: Callable[[dict[str, float]], float],
    *,
    method: str,
    seed: int,
    budget: int = 12,
    initial: int = 4,
    pool_power: int = 7,
) -> SearchResult:
    if method not in ("botorch", "sklearn", "random"):
        raise ValueError("Unknown football search method.")
    if not 2 <= initial <= budget <= 2**pool_power:
        raise ValueError("Search budget must fit the pool and common initial design.")
    pool = qmc.Sobol(d=3, scramble=True, seed=seed).random_base2(pool_power)
    chosen: list[int] = []
    losses: list[float] = []
    trials: list[dict[str, Any]] = []
    for step in range(budget):
        remaining = np.array([i for i in range(len(pool)) if i not in chosen])
        start = time.perf_counter()
        if step < initial or method == "random":
            index = int(remaining[0])
        else:
            select = _botorch_choice if method == "botorch" else _sklearn_choice
            index = int(remaining[select(pool[chosen], np.array(losses), pool[remaining])])
        overhead = time.perf_counter() - start
        params = decode(pool[index])
        start = time.perf_counter()
        loss = float(evaluator(params))
        if not np.isfinite(loss):
            raise ValueError("A failed/nonfinite evaluation cannot be silently dropped.")
        chosen.append(index)
        losses.append(loss)
        trials.append(
            {
                "step": step + 1,
                "pool_index": index,
                **params,
                "loss": loss,
                "best_loss": min(losses),
                "acquisition_seconds": overhead,
                "evaluation_seconds": time.perf_counter() - start,
            }
        )
    best = int(np.argmin(losses))
    return SearchResult(method, seed, decode(pool[chosen[best]]), losses[best], tuple(trials))
