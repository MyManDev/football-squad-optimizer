# Deployment configuration

Configuration for the advice backend and its supporting processes. Every file here is an
example or a definition: it holds placeholders, never secrets, and nothing here is applied by
committing it. The static website is deployed by the `Deploy Pages` workflow and needs no file
here ([ADR 0004](../docs/architecture/decisions/0004-cloudflare-pages-deployment.md)).

## The topology these files describe

[ADR 0006](../docs/architecture/decisions/0006-backend-hosting.md) decides that the advice API
and the advice worker are one container image (the root `Dockerfile`) run as two processes
that share one store:

| Process | Command | Port |
| --- | --- | --- |
| API | `uvicorn --factory squadopt.api.runtime:build_app` | 8000 |
| Worker | `python -m squadopt.platform.advice_worker` | 9091, for metrics and health only |

The API answers from the cache or queues a job; the worker solves the job with CP-SAT and
writes the answer. Workers scale by adding processes.

## Files

| File | What it deploys | Read with |
| --- | --- | --- |
| `compose.yaml` | The API and one worker on a single Docker host, from a tested image digest, with the shared store and the published tree mounted | [Backend runbook, one host with Compose](../docs/backend_runbook.md#one-host-with-compose) |
| `backend.env.example` | The environment `compose.yaml` reads: the image digest, the allowed site origins and the host paths of the store, the published tree, the captures and the handoffs | The same section |
| `containerapp.yaml` | ADR 0006's initial topology as one Azure Container Apps definition; applying it creates paid resources | [Backend runbook, Azure Container Apps](../docs/backend_runbook.md#azure-container-apps) |
| `cloudflared/config.example.yml` | A Cloudflare Tunnel that exposes only the API at `squadopt-api.mymandev.com`, from a Windows machine | [Backend free hosting, the tunnel](../docs/backend_free_hosting.md#2-the-tunnel) |
| `club-news.settings.example.toml` | The private model settings of the club-news acquisition command; the browser and the advice API never read it | [Club news configuration](../docs/club_news_configuration.md) |

Copy an example outside Git, replace its placeholders, and keep the copy private.

## What runs today

The API and its workers run natively on the owner's Windows PC, started by
`scripts/run_backend_local.ps1` and kept up by the `SquadOptBackendWatch` scheduled task, and
are reachable only through the `squadopt-api` Cloudflare Tunnel
([backend free hosting](../docs/backend_free_hosting.md)).
[ADR 0009](../docs/architecture/decisions/0009-advice-backend-hosting-options.md) compares other
hosts and is proposed, not decided, and issue #988 decides whether the backend moves off the PC
or is retired in favour of the device solver.
