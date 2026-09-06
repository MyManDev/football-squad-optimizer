"""The api process's composition: a wired application, and the factory uvicorn calls.

``create_app`` takes its collaborators as arguments and defaults them to ``None``, which
is why the module-level ``app`` serves published views and answers 503 on advice. That
default is deliberate and stays: an api built without a store must not pretend an empty
cache is a computed absence. This module is the other half — the deployment's app, wired
to the real store from the server's environment.

It lives in ``squadopt.api`` rather than in the platform composition root because the
layer contract puts ``api`` *above* ``platform``: platform may not import the web
framework's wiring, so whatever calls ``create_app`` belongs here. Everything below
FastAPI — the store, the queue, the capture context — is built by
``squadopt.platform.backend_runtime`` and handed over intact.

Start the deployment's api with the factory:

    uvicorn --factory squadopt.api.runtime:build_app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI

from squadopt.api.app import create_app
from squadopt.platform.backend_runtime import AdviceBackend, backend_from_environment

__all__ = ["app_for_backend", "build_app"]


def app_for_backend(backend: AdviceBackend) -> FastAPI:
    """Wire one already-built backend into the application.

    Injected rather than constructed here so a test — or a local run against a temporary
    store — builds the same application the deployment does, from the same call.
    """

    return create_app(
        data_root=backend.config.site_data_root,
        advice_store=backend.reader,
        advice_submit=backend.submit,
        allowed_origins=backend.config.allowed_origins,
        metrics=backend.metrics,
        queue_depth=backend.queue_depth,
        readiness=backend.readiness,
    )


def build_app() -> FastAPI:
    """The deployment's application, read from the server's own environment."""

    return app_for_backend(backend_from_environment())
