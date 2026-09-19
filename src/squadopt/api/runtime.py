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

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from uvicorn.main import main as uvicorn_cli

from squadopt.api.app import create_app
from squadopt.platform.advice_observability import (
    API_COUNTER_FAMILIES,
    AdviceLog,
    AdviceMetrics,
    configure_advice_logging,
)
from squadopt.platform.backend_runtime import AdviceBackend, backend_from_environment

__all__ = ["app_for_backend", "build_app"]


def _forwarded_trust() -> dict[str, object]:
    """Describe declared Uvicorn CLI settings, never an observed request address.

    A programmatic server can override its environment. Its settings are unknown to an
    app factory, so do not report the environment as the effective configuration there.
    """
    unknown: dict[str, object] = {"trust_status": "unverified", "trust_source": "unknown launcher"}
    executable = Path(sys.argv[0])
    if not (
        executable.name.lower() in ("uvicorn", "uvicorn.exe")
        or (executable.name == "__main__.py" and executable.parent.name == "uvicorn")
    ):
        return unknown
    # Use Uvicorn's own option parser so CLI flags and UVICORN_* precedence match it.
    # Parsing a context does not invoke the command or start a server.
    with uvicorn_cli.make_context("uvicorn", sys.argv[1:]) as context:
        if context.params["env_file"] is not None:
            # An env file may have changed the environment since CLI parsing. Without
            # that earlier environment we cannot reconstruct its effective options.
            return unknown
        enabled = context.params["proxy_headers"]
        allowed = context.params["forwarded_allow_ips"]
        allow_source = context.get_parameter_source("forwarded_allow_ips")
        source = f"uvicorn {allow_source.name.lower()}" if allow_source else "unknown"
        if allowed is None:
            allowed = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
            source = (
                "FORWARDED_ALLOW_IPS" if "FORWARDED_ALLOW_IPS" in os.environ else "uvicorn default"
            )
        proxy_source = context.get_parameter_source("proxy_headers")
        return {
            "trust_status": "enabled"
            if enabled and any(peer.strip() for peer in allowed.split(","))
            else "disabled",
            "trust_source": source,
            "forwarded_allow_ips": allowed,
            "proxy_headers": enabled,
            "proxy_headers_source": f"uvicorn {proxy_source.name.lower()}"
            if proxy_source
            else "unknown",
        }


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
        jobs_by_status=backend.jobs_by_status,
        readiness=backend.readiness,
    )


def build_app() -> FastAPI:
    """The deployment's application, read from the server's own environment."""

    # Here rather than in ``app_for_backend``: this is the process entry point uvicorn
    # calls, while the injected form is also how tests build the app, and a test that gets
    # handlers attached to a module-level logger has been given a side effect it did not ask
    # for. uvicorn configures only its own loggers, so without this the advice events —
    # every accepted request, every rejection reason — go nowhere.
    configure_advice_logging()
    AdviceLog("api").event("advice_forwarded_trust", **_forwarded_trust())
    return app_for_backend(
        backend_from_environment(metrics=AdviceMetrics(zero_counters=API_COUNTER_FAMILIES))
    )
