# ADR 0012: The FPL forwarder, a separate Worker at /api/v1/fpl/*

- **Status:** accepted by İbo on 2026-11-01, under the owner's handover of the program to him
  (issue #978, comment 6548175771). It takes up the same-origin Worker that
  [ADR 0004](0004-cloudflare-pages-deployment.md) left as an option, and leaves ADR 0004's
  decision, a static Pages site, standing.
- **Date:** 2026-11-01
- **Decider:** İbo, who holds the decisions of #978 and its issues since 2026-10-31
- **Related:** [ADR 0003](0003-measurement-artifacts.md),
  [ADR 0004](0004-cloudflare-pages-deployment.md),
  [ADR 0005](0005-persistence-boundaries.md), [ADR 0006](0006-backend-hosting.md),
  [FPL forwarder probe](../../fpl_forwarder_probe.md),
  [live data source options](../../live_data_source_options.md),
  [official injury discovery](../../operations/official_injury_discovery.md),
  [`fpl_league_standings_v1`](../../contracts/fpl_league_standings_v1.md),
  [`fpl_entry_bundle_v1`](../../contracts/fpl_entry_bundle_v1.md),
  [`week_live_v1`](../../contracts/week_live_v1.md), issues #978, #979, #980, #983 and #1008

## Context

A visitor's browser cannot read FPL. FPL sends no `Access-Control-Allow-Origin` header and sets
`Cross-Origin-Resource-Policy: same-origin`, so a page on `squadopt.mymandev.com` gets nothing
back from `fantasy.premierleague.com`. The site therefore shows only the leagues and entries the
weekly run captured. The owner's direction is that any classic league and any entry should open,
with the plan computed on the visitor's device (#983 steps 3 and 4, #980 comment 6548150068).

ADR 0004 kept the Pages site static and named a same-origin Worker as an option for this, to be
built only if FPL answers requests that leave Cloudflare's network. The probe of #979 measured
that: its verdict was **served**, 147 of 147 scheduled standings probes in its window (#979
comment 6409696405, record #1241).

The owner said yes to #980 and to the two additions of #1008 (comment 6548150068): a trimmed live
week and the member's in-progress week in the entry bundle, both as comment 6409696721 scoped
them. İbo's decisions for the build are #980 comment 6559340452. This record states them.

## Decision

**1. A separate Worker on one route.** The forwarder is `workers/fpl-proxy/`, deployed as the
Worker `squadopt-fpl-proxy` on exactly one route, `squadopt.mymandev.com/api/v1/fpl/*` on the
`mymandev.com` zone, with no `workers.dev` address and no preview addresses. The Pages site is not
changed: its preflight still refuses `functions/` and `_worker.js`, and nothing it serves lives
under `/api/v1/fpl/`. The probe's prefix route, `/api/v1/fpl-probe*`, does not overlap this one.

**2. An allowlist of three GET routes.** Ids are positive integers written without a sign, a
leading zero or a decimal point. The query must be exactly what the route names, once.

| Route | Answers | Upstream reads |
| --- | --- | --- |
| `/api/v1/fpl/standings/{league}?page={1..20}` | [`fpl_league_standings_v1`](../../contracts/fpl_league_standings_v1.md): one page of a classic league | `leagues-classic/{league}/standings/?page_standings={page}`; on a 404 for page 1, `leagues-h2h/{league}/standings/` once, to name a head-to-head league in the refusal, as the capture does |
| `/api/v1/fpl/entry/{entry}/bundle?gw={table gameweek}` | [`fpl_entry_bundle_v1`](../../contracts/fpl_entry_bundle_v1.md): what the device's entry readers take, and the member's current week | `entry/{entry}/`, `entry/{entry}/history/`, `entry/{entry}/transfers/`, the picks of the held week and of each week the Free Hit walk-back passes, the gameweek 1 picks when the history starts there, the current week's picks, and `fixtures/?event={current week}` |
| `/api/v1/fpl/live/{gameweek}` | [`week_live_v1`](../../contracts/week_live_v1.md) without member blocks, for the current week or an earlier one | `event/{gameweek}/live/` and `fixtures/?event={gameweek}` |

Every other path answers a JSON 404; another method on one of the three paths answers a JSON
405. A bundle's table gameweek runs from 2 to the week after the latest started one, so its held
picks have been frozen at a deadline; a live week runs from 1 to the latest started one. Those
two refusals are JSON 404s too, and FPL is asked nothing for them.

**3. Trimmed, versioned documents only.** No answer is FPL's own JSON. Each document carries a
`contract_version` and only the fields its contract lists: the fields the device's readers take
(`web/src/features/league/entryState/parsers.ts` and `prices.ts`, the Python standings reader in
`src/squadopt/data/sources/fpl_live.py`) and the live inputs `week_live_v1` defines. A field FPL
adds is dropped, and an answer whose kept fields are not what the contract says is treated as
FPL failing (decision 5). `bootstrap-static` is never read: the weekly run publishes what the
device needs from it.

**4. The current week comes from the site.** The latest started gameweek and the next deadline
are read from the site's own `/data/fixtures.json` (`fixtures_v1`), kept for 5 minutes per data
centre. A deadline at the current instant has passed, as the capture's `next_open_deadline`
reads it.

**5. Short copies at the edge, and the last good one.** Each document is kept in the Cache API of
the Cloudflare data centre that served it, under a key below `/api/v1/fpl/.cache/v1/` that the
Worker itself answers with 404:

| Document | Kept for |
| --- | --- |
| A standings page | 10 minutes |
| A live week with a fixture not yet finished | 60 seconds |
| A live week whose fixtures are all finished | until the next deadline |
| A bundle while the current week has a fixture not yet finished, or its fixtures could not be read | 10 minutes, and never past the next deadline |
| A bundle once the current week's fixtures are all finished | until the next deadline |
| A league, page or entry FPL answers 404 for | 10 minutes |
| The schedule read from `/data/fixtures.json` | 5 minutes |

After the last deadline of the season, "until the next deadline" is one day, and no fresh copy
is kept longer than seven days. Beside each fresh copy a **last good copy** is kept under its own key,
for two days longer than the fresh one. When FPL answers 429 or 5xx, cannot be reached, or sends
an answer the Worker cannot read, and when the site's fixture list cannot be read, the last good
copy is served unchanged, with its original `source_time` and the header
`x-squadopt-fpl-cache: last-good`. Without one the answer is a JSON 503.

KV is not used. The Free plan allows 1,000 KV writes a day, and a fresh and a last good copy of
every document would spend that within a few hundred requests; the Cache API holds the copies
instead. Copies are per data centre, so two visitors far apart can see copies of different ages;
`source_time` says when each was read.

**6. The capture's honest user agent.** Every request to FPL sends
`squadopt/1.0 (private research; contact via repository owner)`, the `USER_AGENT` of
`src/squadopt/platform/fpl_capture.py`; a test fails if the two part. Cloudflare's own fetch
cache is bypassed (`cacheTtl: 0`), as the probe did, so the copies above are the only ones.

**7. JSON, marked, same origin only.** Every answer, refusals and errors included, is JSON with
`content-type: application/json; charset=utf-8`, `cache-control: no-store` and the header
`x-squadopt-fpl: 1`. A bypassed route falls through to the site's shell with status 200, so a
client rejects any answer without that header or with a wrong `contract_version` and falls back
to the published tree (#983 step 3). No CORS header is sent: only the site's own pages read it.

**8. Limits.** The zone's rate-limiting rule, `starts_with(http.request.uri.path, "/api/v1/")`
with 50 requests per 10 s per IP ([backend free hosting](../../backend_free_hosting.md)), is
written on the path alone, so it counts these routes too, together with the backend's: one
budget per visitor address. The Free plan allows 100,000 Worker requests a day, and every request
counts whether a copy answers it or FPL does. #980 is finished only when one week's count is
recorded under 10 percent of that.

**9. Deployment.** `.github/workflows/deploy-fpl-proxy.yml` is dispatched by hand from the
default branch (`develop`) only, into the `cloudflare-workers` environment with its two secrets,
with the probe's pinned `wrangler-action` and wrangler 4.123.0. It deploys or deletes. Its smoke
asks `/api/v1/fpl/smoke`, which is none of the three routes, and passes only on the Worker's JSON
404 with the marker header, so the smoke asks FPL nothing. The node tests run in the CI web job
and again before a deploy. The first deploy follows İbo's yes after a preview of the routes'
answers, and needs the Workers token renewed before it expires on 2026-11-05.

## Terms note (D4)

**What was read.** Two readings of the Premier League terms are recorded in this repository:

- [Live data source options](../../live_data_source_options.md), checked on 2026-08-13. The terms
  permit downloading and printing "as is reasonable for your own private and personal use", and
  say the website and app "must not be used in any other way, including for commercial purposes,
  and you may not otherwise reproduce, re-utilise or redistribute it", naming the creation of a
  database as an example. That reading set the posture the capture keeps: local snapshots, a
  private and non-commercial project, nothing published or redistributed.
- [Official injury discovery](../../operations/official_injury_discovery.md), checked on
  2026-10-02. The terms restrict reuse, database extraction, redistribution and deep links
  without written approval, and the repository owner confirmed that no redistribution permission
  is held.

**What it means here.** On a strict reading, answering a visitor with data the Worker read from
FPL is redistribution, and no permission for it is held. This is a factual reading, not legal
advice.

**What the forwarder does to keep within as little of it as it can.**

- It relays, per request, only what that visitor asked for: one league page, one entry, or one
  week's live points. It reads nothing on a schedule and nothing nobody asked for.
- It serves trimmed, versioned documents holding the fields the device reads, never FPL's own
  JSON, and never `bootstrap-static`. The trimmed live data, `week_live_v1`, is covered by this
  note, as #1008's coordination (#980 comment 6046267275) required.
- It keeps no database: no KV, no D1, no other store. The only copies are the short ones of
  decision 5, in each data centre's cache, which expire by themselves.
- It records no visitor's request: the Worker's invocation logs are off, and its own log lines
  name a route's kind, a failure's kind and an HTTP status, never a league or entry id.
- The project stays private and non-commercial.

**Who accepted the risk.** İbo accepted this risk on 2026-11-01, before the first release, under
the owner's handover of the program (#978 comment 6548175771). If permission is refused, FPL
objects, or the project stops being private and non-commercial, the forwarder is deleted with
its workflow and the site falls back to the published tree.

## Consequences

- A visitor's device can read any classic league of up to 20 pages, any entry, and the live
  week, which #983 steps 3 and 4 and #1008's source A build on. Neither is wired by this record.
- A third deployment surface exists beside Pages and the backend. The site must keep working
  from the published tree when the forwarder is absent, down or refusing.
- The Free plan limits the CPU time of each request. The live route parses FPL's whole live
  document for a week, whose size and parse time this repository has not measured; the preview
  before the first release reads it.
- FPL's behaviour that no capture here records is read defensively: a 404 for a classic page 1
  is named head-to-head only when FPL's head-to-head table declares the league (as
  `classic_standings` in `src/squadopt/platform/fpl_capture.py` assumes), and the `fixtures`
  answer is filtered by `event` even though it is asked for one week.

## Rollback

Dispatch the workflow with `delete`. The route stops answering as the Worker within a minute or
so, the client rejects the site's shell that answers instead, and every page falls back to the
published tree. The Worker owns no data.

## When to revisit

If one week's request count approaches 10 percent of the Free plan's daily allowance; if FPL
starts refusing the forwarder's requests in a way the last good copy cannot cover; if permission
to redistribute is obtained or refused; or if the device needs a field the contracts do not
carry, which is a new contract version, not an edit.
