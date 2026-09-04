# ADR 0004 — Publish tested static artifacts with Cloudflare Pages

- **Status:** accepted
- **Date:** 2026-08-20
- **Decider:** platform owner
- **Related:** [ADR 0003](0003-measurement-artifacts.md),
  [deployment runbook](../../deployment_runbook.md)

## Context

The product website is a static React/Vite application. CI builds `web/dist`; the browser
loads committed `ui_view_v1` JSON and makes no runtime API call. Deployment therefore needs
to publish the artifact CI already tested, preserve React Router deep links, and prevent
weekly JSON from remaining stale. It does not need an application server, database, or
runtime secret.

`develop` is the integration trunk and `main` is release history. Production is a separately
controlled pointer: a decision view is published before each deadline and a settled view is
published after results arrive. A merge to `main` alone must not silently change the live
site.

The first draft deployed on every CI push and pull request. That does not fit the measured
repository traffic: 79 eligible CI events occurred on 2026-08-19 and 41 by 17:30Z on
2026-08-20. Of 133 pull requests opened over the measured seven-day window, only nine touched
`web/**`. Sending Python and documentation changes to Pages would consume the Free-plan
deployment allowance without producing a useful preview.

The repository also lacked a classification for `web/public/data`. ADR 0003 defines records,
evidence, and operational state, but this directory is the public browser-facing projection
of accepted operational data.

## Decision

Use **Cloudflare Pages Direct Upload**. The `web` CI job is the sole builder and uploads
`web/dist` as the `site` GitHub artifact. Deployment downloads those exact bytes and never
runs a second build.

Use two trusted deployment paths in a workflow stored on the GitHub default branch:

1. **Preview:** after successful PR CI, query the PR files and deploy only a current,
   same-repository PR against `develop` that changes or renames a path under `web/**`. The
   branch is `pr-N`. The privileged job never checks out the PR branch or executes a script
   from its artifact; trusted tooling validates and transports the artifact as data.
2. **Production:** a human dispatches the workflow with an existing annotated site tag. The
   workflow resolves the tag to a commit, requires that commit to be in `main`, locates the
   successful `main`-push CI run for the same SHA, and deploys that run's unexpired `site`
   artifact with branch `main`. There is no push deployment and no cron.

The project name is an API identifier, not an assumed hostname. Before upload, the workflow
reads and validates the project's actual `*.pages.dev` subdomain; Cloudflare may add a suffix
when the preferred hostname is occupied. Preview and production identity checks use that API
value rather than constructing a hostname from the project name.

Production tags are phase-qualified, immutable, and never reused:

- `site-2026-27-gw01-decision`
- `site-2026-27-gw01-settled`
- `site-2026-27-gw01-fix1` for a later corrective publication

Existing season tags such as the historical `v2026-27.gw01` release pointer and the actual
`run-2026-27-gw01` operational freeze retain their original meanings and are never moved to
identify site publications. Every production Actions summary records the site tag, peeled
commit SHA, source CI run, Cloudflare deployment URL, and smoke result.

Cloudflare credentials live in the `cloudflare-pages` GitHub Environment, whose deployment
branch rule permits only the default `develop` branch. They are never attached to the CI job,
a PR-triggered job, a job-level environment, or an untrusted checkout. The Wrangler action,
artifact transport actions, and other actions in the privileged workflow are pinned to full
commit SHAs. Deployment failures remain outside the required CI workflow, but they fail their
own deployment workflow visibly; a failed production smoke must not look green.

Use the Pages Free plan while the application remains static. The operational budget treats
500 deployments per month as the ceiling. Before each upload, query all project deployments
for the current UTC day:

- automatic previews stop at eight, reserving two slots for production and a retry;
- production stops loudly at ten total deployments;
- all Cloudflare deployment records count, including failed or cancelled attempts;
- each eligible successful PR run uploads because the tested merge base is part of its state;
  production dispatches always reassert the canonical alias;
- one repository-wide FIFO concurrency group serializes budget check and upload.

This is an emergency circuit breaker, not the routing rule. The primary controls are
`web/**`-only previews and two deliberate production publications per gameweek.

The deployment has no top-level `404.html`. Cloudflare Pages therefore applies its native SPA
fallback when no asset matches, and React Router handles deep links. A catch-all `_redirects`
rule is not used because it can rewrite JSON and JavaScript requests to `index.html`.
`web/public/_headers` requires revalidation of stable `/data/*` URLs and permits long caching
for Vite's content-hashed assets. Privileged preflight also rejects symlinks, Pages Functions,
`_worker.js`, more than 20,000 files, and files larger than 25 MiB.

`web/public/data` is **published view data**:

- generated by `python -m scripts.build_site --out web/public` from accepted operational
  inputs;
- reproducible and never edited by hand;
- committed so a release and its visible data are one reviewable revision;
- public and forbidden from containing secrets or licence-restricted raw captures.

It is a delivery representation, not a source of truth. If it disagrees with the ledger,
regenerate it; do not repair the JSON directly.

## Why not GitHub Pages

GitHub Pages can host the current static output, but Cloudflare Pages provides direct-upload
preview aliases and convenient SPA behavior. It also leaves an optional Workers/Pages
Functions path if a future browser integration needs a same-origin proxy. That is only an
option: this decision introduces no server-side function.

The FastAPI service under `src/squadopt/api` cannot run on Cloudflare Pages and requires a
separate backend-hosting decision before it is exposed publicly.

## Rollback

Promote the previous known-good Cloudflare production deployment identified by its immutable
site tag and commit SHA, then repeat all smoke checks and record which tag is live. Never move
the tag. If the published content is wrong, fix or revert through `develop` and `main`, then
publish a new phase-qualified `fixN` tag. If only transport failed, redeploy the exact retained
CI artifact without rebuilding it.

Because production is deliberately decoupled from `main`, `main` may legitimately be ahead of
the live tag. Rollback does not require rewriting repository history.

## When to revisit

Reconsider the platform if the product gains stateful backend workloads, private data, or
server-side compute. Reconsider Direct Upload only if Cloudflare becomes the authoritative
builder; that requires a new Pages project because Direct Upload projects cannot be converted
to Git integration.

## Consequences

- Cloudflare account configuration, a protected GitHub Environment, and two environment
  secrets become operational dependencies, but never application runtime dependencies.
- Useful web PRs retain preview URLs; Python and docs PRs consume no Pages deployments.
- Production changes only after an explicit, tagged dispatch and may lag `main` by design.
- The same built bytes are tested, retained by GitHub, validated as static, and deployed.
- A scheduled unattended release cannot publish the wrong `main` state at the deadline.
