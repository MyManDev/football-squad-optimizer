"""Recipient-only training keeps exact marginal math and excludes every count-head fit."""

from dataclasses import asdict, replace
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from tests.unit.test_football_observed_tactical import (
    CUTOFF,
    observation,
    projection,
    replayed,
    sha,
)
from tests.unit.test_football_observed_tactical import (
    fit as fit_full,
)

from squadopt.prediction import football_observed_tactical as shared
from squadopt.prediction.football_observed_tactical_recipients import (
    FIT_SCOPE,
    MODEL_VERSION,
    ObservedTacticalRecipientModel,
)
from squadopt.prediction.football_observed_tactical_serving import (
    export_observed_tactical_serving_model,
    read_observed_tactical_serving_model,
)


def fit(rows: tuple[Any, ...], **kwargs: Any) -> ObservedTacticalRecipientModel:
    return ObservedTacticalRecipientModel().fit(
        rows,
        cutoff=CUTOFF,
        target_season="2026-27",
        target_gameweek=5,
        allowed_seasons=kwargs.pop("allowed_seasons", ("2024-25",)),
        **kwargs,
    )


def test_only_recipient_optimizers_run_and_match_full_model_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = tuple(observation(i) for i in range(3))
    full = fit_full(rows)
    before = full.metadata_json
    original = shared._optimize
    called = []

    def optimize(objective: Any, width: int, iterations: int, head: str) -> Any:
        assert head in ("goals", "assists")
        called.append(head)
        return original(objective, width, iterations, head)

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("Recipient training accessed the inactive physical head")

    monkeypatch.setattr(shared, "_optimize", optimize)
    monkeypatch.setattr(shared, "team_features", forbidden)
    monkeypatch.setattr(shared, "_pair_terms", forbidden)
    model = fit(rows)
    assert called == ["goals", "assists"]
    assert model.metadata.model_version == MODEL_VERSION
    assert model.metadata.fit_scope == FIT_SCOPE
    assert model.metadata.goal_transform == full.metadata.goal_transform
    assert model.metadata.assist_transform == full.metadata.assist_transform
    assert model.metadata.goal_gamma == full.metadata.goal_gamma
    assert model.metadata.assist_gamma == full.metadata.assist_gamma
    assert model.metadata.goal_events == full.metadata.goal_events
    assert model.metadata.assist_events == full.metadata.assist_events
    assert model.metadata.optimizers == full.metadata.optimizers[1:]
    assert model.metadata.training_receipts == full.metadata.training_receipts
    assert full.metadata_json == before
    assert "beta" not in asdict(model.metadata) and "team_transform" not in asdict(model.metadata)
    p = projection(current=True)
    result = model.predict_recipients(p)
    assert result.home == full.predict_recipients(p).home
    assert result.away == full.predict_recipients(p).away
    assert result.model_version == MODEL_VERSION and result.model_sha256 != full.model_sha256
    raw = export_observed_tactical_serving_model(model)
    serving = read_observed_tactical_serving_model(raw, expected_sha256=sha(raw))
    compact = serving.predict_recipients(p)
    assert serving.metadata.fit_scope == FIT_SCOPE
    assert compact.home == result.home and compact.away == result.away
    assert compact.model_version == MODEL_VERSION
    assert compact.serving_receipt.original_metadata_sha256 == model.model_sha256


def test_recipient_training_checks_every_header_before_any_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = observation(), observation(1)
    second = replace(second, projection=replace(second.projection, season="2027-28"))
    seen = []
    monkeypatch.setattr(shared, "validate_outcome", lambda row: seen.append(row))
    with pytest.raises(ValueError, match="before outcome"):
        fit((first, second))
    assert seen == []


@pytest.mark.parametrize("flag", [False, 1, "true", None])
def test_recipient_training_released_season_requires_strict_opt_in(flag: Any) -> None:
    with pytest.raises(ValueError):
        fit((replayed(),), allowed_seasons=("2025-26",), allow_released_2025_26=flag)


def test_recipient_training_explicit_replay_opt_in_and_current_refusal() -> None:
    o = replayed()
    model = fit((o,), allowed_seasons=("2025-26",), allow_released_2025_26=True)
    assert model.metadata.allow_released_2025_26 is True
    assert model.metadata.training_receipts[0].generated_at == o.projection.generated_at
    with pytest.raises(ValueError, match="prospective"):
        model.predict_recipients(o.projection)


def test_recipient_optimizer_failure_retains_diagnostics_and_previous_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = fit((observation(),))
    before = model.metadata_json

    def stopped(objective: Any, x: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            x=x, success=False, status=1, nit=500, nfev=501, fun=3.25, message="iteration limit"
        )

    monkeypatch.setattr(shared, "minimize", stopped)
    with pytest.raises(shared.ObservedTacticalOptimizationError) as caught:
        model.fit(
            (observation(),),
            cutoff=CUTOFF,
            target_season="2026-27",
            target_gameweek=5,
            allowed_seasons=("2024-25",),
        )
    diagnostic = caught.value.diagnostics
    assert diagnostic["head"] == "goals"
    assert diagnostic["max_iter"] == diagnostic["nit"] == 500
    assert diagnostic["status"] == 1 and diagnostic["success"] is False
    assert diagnostic["nfev"] == 501 and diagnostic["reported_objective"] == 3.25
    assert diagnostic["message"] == "iteration limit"
    assert diagnostic["coefficients_finite"] is True
    assert model.metadata_json == before


def test_optimizer_diagnostics_never_coerce_invalid_declarations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = SimpleNamespace(
        x=np.asarray([True]), success=1, status=True, nit="500", nfev=None, fun="3.25", message=None
    )
    monkeypatch.setattr(shared, "minimize", lambda *args, **kwargs: result)
    with pytest.raises(shared.ObservedTacticalOptimizationError) as caught:
        shared._optimize(lambda x: (0.0, x), 1, 500, "goals")
    diagnostic = caught.value.diagnostics
    assert all(
        diagnostic[k] is None
        for k in ("success", "status", "nit", "nfev", "reported_objective", "message")
    )
    assert diagnostic["coefficients_finite"] is False


def test_recipient_only_missing_evidence_support_control_and_metadata_refusal() -> None:
    o = observation(missing=True)
    o = replace(o, credits=tuple(replace(c, assists=0) for c in o.credits))
    model = fit((o,))
    assert all(r.head == "goals" for r in model.metadata.optimizers)
    assert model.metadata.assist_events == 0 and all(g == 0 for g in model.metadata.assist_gamma)
    p = projection(current=True, missing=True)
    with pytest.raises(ValueError, match="credited-event support"):
        model.predict_recipients(p)
    control = model.predict_recipients(p, control=True)
    assert [x.goal_share for x in control.home.players] == [
        x.native_goal_share for x in p.home.players
    ]
    with pytest.raises(ValueError, match="Boolean"):
        model.predict_recipients(p, control=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="target window"):
        model.predict_recipients(replace(p, gameweek=4), control=True)
    fitted = model._fitted
    assert fitted is not None
    model._fitted = replace(
        fitted, metadata=replace(fitted.metadata, fit_scope="fabricated_count_head")
    )
    with pytest.raises(ValueError, match="metadata"):
        _ = model.metadata
