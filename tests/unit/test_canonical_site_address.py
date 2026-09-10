"""The address members actually open is a repository fact, not folklore.

The Pages project serves two hostnames: the project's `*.pages.dev` subdomain and the custom
domain `squadopt.mymandev.com`. Until this module existed the repository named only the first,
and the first is the one nobody the site is for can reach. Measured on 2026-09-09 from the
owner's network: TCP to `squadopt.pages.dev:443` completes in ~29 ms and the peer then resets
the connection before any TLS record; `developers.cloudflare.com` negotiates TLS and answers
200 over the same path, and it still does when curl is forced to send that request to the very
IP the `pages.dev` name resolves to. Point the other way — send SNI `squadopt.pages.dev` to a
Cloudflare IP that answers 200 for another name — and the reset comes back. The filter keys on
the hostname, so no Cloudflare-side change and no retry can make `pages.dev` the address given
to members. `docs/handover_2026-08-23.md` recorded the same unreachability from a second
network three weeks earlier.

Two consequences are pinned here because both failed silently rather than loudly:

- **CORS.** The backend's allowlist named only the `pages.dev` origin. The advice backend is
  being wired up now; a browser on the custom domain would have been refused by the allowlist
  on its first cross-origin request, and the refusal would have looked like a backend fault.
- **The deployment smoke.** Production smoked the `pages.dev` alias only, so a publication that
  never reached the address people open would report green.

The third fact — that the two files below must keep saying the same thing as the code — is why
this is a test and not a comment. The origins the runbook tells an operator to set and the
hostname the workflow smokes are both copies of `CANONICAL_SITE_ORIGIN`, and copies drift.
"""

import re
from pathlib import Path

from fastapi.testclient import TestClient

from squadopt.api.app import create_app
from squadopt.platform.backend_runtime import (
    CANONICAL_SITE_ORIGIN,
    PAGES_ALIAS_ORIGIN,
    SITE_ORIGINS,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
BACKEND_RUNBOOK = REPOSITORY_ROOT / "docs" / "backend_runbook.md"
DEPLOY_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "deploy-pages.yml"

PREFLIGHT = "/api/v1/leagues/313686/entries/2199732/advice"


def _runbook_origins() -> tuple[str, ...]:
    """The allowlist exactly as an operator would copy it out of the runbook."""

    line = re.search(
        r"^SQUADOPT_BACKEND_ALLOWED_ORIGINS=(.*)$",
        BACKEND_RUNBOOK.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert line is not None, "the runbook no longer shows the CORS allowlist variable"
    return tuple(part.strip() for part in line.group(1).split(",") if part.strip())


def test_a_browser_on_the_canonical_address_is_not_refused_by_cors(tmp_path: Path) -> None:
    """The deployed allowlist, taken from the runbook, admits a browser on the real address.

    Driven from the runbook rather than from the constant on purpose: the runbook is what
    configures the running backend, so this fails if the two ever part company — which is the
    state it was written to end.
    """

    application = create_app(data_root=tmp_path / "site", allowed_origins=_runbook_origins())
    client = TestClient(application, raise_server_exceptions=False)

    for origin in (CANONICAL_SITE_ORIGIN, PAGES_ALIAS_ORIGIN):
        response = client.options(
            PREFLIGHT,
            headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
        )
        assert response.headers.get("access-control-allow-origin") == origin

    denied = client.options(
        PREFLIGHT,
        headers={"Origin": "https://elsewhere.example", "Access-Control-Request-Method": "POST"},
    )
    assert denied.headers.get("access-control-allow-origin") is None


def test_the_backend_runbook_configures_exactly_the_published_origins() -> None:
    """What an operator copies into the deployment is the allowlist the code names.

    Order matters only as documentation — the canonical address is written first because it is
    the one that has to work — but membership is the assertion.
    """

    assert _runbook_origins() == SITE_ORIGINS


def test_production_smokes_the_address_members_open_as_well_as_the_alias() -> None:
    """A publication that has not reached the canonical host must not report green.

    The `pages.dev` check stays: it is the project alias the identity-verified deployment is
    asserted onto, and removing it would trade one blind spot for another.
    """

    workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")
    production = workflow.split("Deploy exact production artifact", 1)
    assert len(production) == 2, "the production job no longer has its upload step"
    production_steps = production[1]

    assert 'smoke-deployment.mjs "$DEPLOYMENT_URL"' in production_steps
    assert 'smoke-deployment.mjs "$CANONICAL_URL"' in production_steps
    assert f"CANONICAL_URL: {CANONICAL_SITE_ORIGIN}" in production_steps
