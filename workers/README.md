# Cloudflare Workers

Workers deployed separately from the static website. The website on Cloudflare Pages stays
static: its deployment check refuses `functions/` and `_worker.js`
([ADR 0004](../docs/architecture/decisions/0004-cloudflare-pages-deployment.md)), so any server
code at the edge lives here, as its own Worker on its own route, with its own workflow and
token.

| Worker | Purpose | Deployed by | Tested by | Document |
| --- | --- | --- | --- | --- |
| [`fpl-probe/`](fpl-probe/README.md) | Measures whether the FPL API answers requests that leave Cloudflare's network | `.github/workflows/deploy-fpl-probe.yml`, dispatched by hand from the default branch | The `FPL probe worker tests` step of the CI web job | [FPL forwarder probe](../docs/fpl_forwarder_probe.md) |

The probe is the prerequisite for an FPL forwarder Worker at `/api/v1/fpl/*` on the site's host,
which would let a member's browser read FPL through the site's own origin. Issue #979 tracks the
probe's token, environment and measurement run; issue #980 tracks the forwarder, which is built
only after the probe returns a served verdict.

A new Worker gets its own folder here with a README, its own deployment workflow and its own
tests in the CI web job, and a row in this table and in the deployment units of the
[architecture overview](../ARCHITECTURE.md#4-deployment-units).
