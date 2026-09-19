"""Synthetic backend apps whose API clock stays at their capture's own instant."""

from datetime import datetime

from fastapi import FastAPI

from squadopt.api.runtime import app_for_backend
from squadopt.platform.advice_observability import (
    API_COUNTER_FAMILIES,
    AdviceMetrics,
    configure_advice_logging,
)
from squadopt.platform.backend_runtime import AdviceBackend, backend_from_environment


def app_for_capture(backend: AdviceBackend) -> FastAPI:
    identity = backend.contexts.identity()
    assert identity is not None, "the synthetic backend must hold a readable capture"
    captured = datetime.fromisoformat(identity.inputs.captured_at_utc)
    return app_for_backend(backend, utc_now=lambda: captured)


def build_app() -> FastAPI:
    """Uvicorn factory for disposable integration fixtures, never production."""

    configure_advice_logging()
    return app_for_capture(
        backend_from_environment(metrics=AdviceMetrics(zero_counters=API_COUNTER_FAMILIES))
    )
