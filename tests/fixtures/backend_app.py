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


def app_for_capture(backend: AdviceBackend, captured_at_utc: str) -> FastAPI:
    captured = datetime.fromisoformat(captured_at_utc)
    return app_for_backend(backend, utc_now=lambda: captured)


def build_app(captured_at_utc: str) -> FastAPI:
    """Build a disposable integration app with an explicitly supplied fixture clock."""

    configure_advice_logging()
    return app_for_capture(
        backend_from_environment(metrics=AdviceMetrics(zero_counters=API_COUNTER_FAMILIES)),
        captured_at_utc,
    )


if __name__ == "__main__":
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("captured_at_utc")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    uvicorn.run(build_app(args.captured_at_utc), host="127.0.0.1", port=args.port)
