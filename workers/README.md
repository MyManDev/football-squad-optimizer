# Cloudflare Workers

Workers deployed separately from the static website. The website on Cloudflare Pages stays
static: its deployment check refuses `functions/` and `_worker.js`
([ADR 0004](../docs/architecture/decisions/0004-cloudflare-pages-deployment.md)), so any server
code at the edge lives here, as its own Worker on its own route, with its own workflow and
token.

| Worker | Purpose | Deployed by | Tested by | Document |
| --- | --- | --- | --- | --- |
| [`fpl-probe/`](fpl-probe/README.md) | Measures whether the FPL API answers requests that leave Cloudflare's network | `.github/workflows/deploy-fpl-probe.yml`, dispatched by hand from the default branch | The `FPL probe worker tests` step of the CI web job | [FPL forwarder probe](../docs/fpl_forwarder_probe.md) |
| [`fpl-proxy/`](fpl-proxy/README.md) | The FPL forwarder: reads FPL on a visitor's request and answers at `/api/v1/fpl/*` with trimmed, versioned documents | `.github/workflows/deploy-fpl-proxy.yml`, dispatched by hand from the default branch | The `FPL forwarder worker tests` step of the CI web job | [ADR 0012](../docs/architecture/decisions/0012-fpl-forwarder.md) |

The probe was the prerequisite for the FPL forwarder Worker at `/api/v1/fpl/*` on the site's
host, which lets a member's browser read FPL through the site's own origin. Issue #979 tracked
the probe's token, environment and measurement run, and its verdict was served; issue #980 tracks
the forwarder, `fpl-proxy/`.

A new Worker gets its own folder here with a README, its own deployment workflow and its own
tests in the CI web job, and a row in this table and in the deployment units of the
[architecture overview](../ARCHITECTURE.md#4-deployment-units).
