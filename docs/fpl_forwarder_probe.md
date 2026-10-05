# FPL forwarder probe

The owner approved a separate Cloudflare Worker as the future FPL forwarder at
`https://squadopt.mymandev.com/api/v1/fpl/*`. A browser cannot read FPL itself: FPL sends no
CORS header and sets `Cross-Origin-Resource-Policy: same-origin`, so a page on the site's origin
gets nothing back from `fantasy.premierleague.com`. A forwarder on the site's own host would
fetch FPL and answer the page.

Building it on Cloudflare only makes sense if FPL answers requests that leave from Cloudflare's
network. Many services challenge or refuse data-centre traffic, and nothing in this repository
has measured whether FPL does. The probe measures that first, for 3 to 5 days, at a rate too low
to matter to FPL, before any forwarder code is written.

The probe is not the forwarder. It forwards nothing to anyone: the only things it answers with
are its own small records. The Pages site is not touched and stays static
([ADR 0004](architecture/decisions/0004-cloudflare-pages-deployment.md),
[ADR 0006](architecture/decisions/0006-backend-hosting.md)): the probe is a separate Worker on a
route of its own, and the site artifact's preflight still refuses `functions/` and `_worker.js`.

## What it calls, and how often

| Target | Why |
| --- | --- |
| `https://fantasy.premierleague.com/api/event-status/` | The cheapest FPL answer, a few hundred bytes. |
| `https://fantasy.premierleague.com/api/leagues-classic/352490/standings/` | The answer a forwarder would exist to serve: the league table members open. |

- **Every 30 minutes** a cron trigger asks each target once, one after the other: two requests
  to FPL per run, 48 runs and **about 96 requests a day**. Each request gives up after 10 s.
- Each request sends the same honest user agent as the capture (`USER_AGENT` in
  `src/squadopt/platform/fpl_capture.py`; a test fails if the two part company) and is fetched
  with `cacheTtl: 0`, so a copy in Cloudflare's own cache cannot answer in FPL's place and
  hide a refusal.
- A scheduled run has no incoming request to say which Cloudflare data centre it is in, so it
  first reads `https://www.cloudflare.com/cdn-cgi/trace` once. That request goes to Cloudflare,
  not FPL.
- **The probe stops by itself.** The deploy workflow passes `PROBE_UNTIL`, 7 days after the
  deploy. From then on the cron still wakes the Worker every 30 minutes, but it asks FPL
  nothing and writes nothing, and the live probe answers `410`. A deploy without `PROBE_UNTIL`
  probes nothing at all. The results path keeps answering until the Worker is deleted.
- `GET /api/v1/fpl-probe/now` runs one live probe of both targets on request, only for a
  request that carries the header `x-squadopt-probe: now`; without it the answer is `400` and
  FPL is asked nothing. A page on another site cannot add that header without a CORS preflight,
  which the Worker never grants, so nobody's browser can be made to run the probe. The live
  probe runs **at most once a minute and 48 times a UTC day for all callers together**; any
  other call gets `429` and asks FPL nothing. The gate is one KV value: when the last live
  probe ran, on which UTC day, and how many ran that day. Concurrent requests in one Worker
  instance cannot pass it together, but KV takes up to a minute to reach other data centres, so
  callers far apart can still get a live probe each within the same minute; that is the gate's
  slack. The zone's rate-limit rule on `/api/v1/` (50 requests per 10 s per IP) also stands in
  front of both paths.

The Worker answers only `GET /api/v1/fpl-probe` and `GET /api/v1/fpl-probe/now`. Its route,
`squadopt.mymandev.com/api/v1/fpl-probe*` on the `mymandev.com` zone, is a prefix: every path
that starts with `/api/v1/fpl-probe`, with any query string, reaches the Worker, and every path
but those two, and every other method, gets a `404` JSON answer. The site has nothing under that
prefix. The Worker has no `workers.dev` address, and every answer carries
`cache-control: no-store` and the header `x-squadopt-probe: 1`, by which the deploy workflow
tells the Worker from anything else answering the path.

## What it stores, and for how long

One record per probe, in the KV namespace titled `squadopt-fpl-probe`, under
`r:<run start time, ISO>:<target index>`, **expiring after 14 days**. The namespace also holds
one key, `now:gate`, the live probe's gate (`last`, `day`, `count`), which expires after two
days.

| Field | Meaning |
| --- | --- |
| `at` | When this request started (ISO, UTC). |
| `trigger` | `cron` for the schedule, `now` for a live probe. |
| `target` | The URL asked. |
| `status` | The HTTP status, or `null` when no answer arrived. |
| `ms` | Time to the full answer, or to the failure. |
| `bytes` | Size of the answer's body, or `null`. |
| `content_type` | The answer's `content-type`. |
| `json` | Whether the body parses as a JSON object or array. |
| `head` | Only for an answer that is not JSON: its first 120 characters, whitespace folded. `null` otherwise. |
| `colo` | The Cloudflare data centre a scheduled run was in; `null` for a live probe. |
| `error` | `timeout after 10000 ms`, or a short description of a network failure; `null` when an answer arrived. |

Nothing else of an answer is kept: a JSON answer leaves only its size behind, so no league
member's name or score is stored. Of a caller, only this is kept: a live probe's two records
carry the time it ran (`at`), and the gate counts it. A live record keeps no data centre,
because that would say where the caller is. Workers Logs keep the Worker's own `probe` lines
but not the per-request invocation logs (`invocation_logs = false` in `wrangler.toml`).

On the Workers Free plan KV accepts 1,000 writes and 1,000 list operations a day, per account,
counted from 00:00 UTC.

- **Writes.** The schedule uses 96 a day. Each live probe uses three (the gate and two
  records), so the daily cap of 48 holds the live path to 144 and the day to 240. The cap holds
  within a data centre, short of a rare race between two Worker instances there; callers in
  many data centres at once could each get past it before KV reaches them, which takes a
  deliberate, distributed effort. A record that could not be written shows up in the summary
  as a gap (`longest_gap_minutes`), and scheduled records lost from the verdict's window count
  toward `too few probes`.
- **Lists.** Building the results answer lists the records once, or twice past 1,000 records.
  The built answer is kept in the data centre's cache for 5 minutes, so a burst of readers in
  one place costs one build; `generated_at` says when it was built. Readers in many data
  centres at once could still use up the day's lists; the results path then answers `500`
  until 00:00 UTC, while the schedule keeps writing its records.

## How to read the results

```bash
curl -s https://squadopt.mymandev.com/api/v1/fpl-probe | python -m json.tool
```

The answer holds `generated_at`, `probe_until`, `records` (every stored record, oldest first)
and `summary`:

- `summary.by_trigger`: how many records the schedule (`cron`) and the live probe (`now`) left.
- `summary.scheduled` and `summary.live`: per target, for the schedule's records and the live
  probe's records apart, the number of `probes`, how many were `served` (HTTP 200 with a JSON
  body) and `served_share`, `by_status` (counts by HTTP status, with `timeout` and `error` for
  probes that got no answer), `first_at` and `last_at`, `span_hours`, `longest_failure_run`
  (`length`, `from`, `to`) and `longest_gap_minutes` between two probes.
- `summary.verdict`: the rule below applied to the scheduled standings probes: the window
  (`window_from`, `window_to`), the probes in it (`window_probes`, `window_served`, `share`),
  `min_probes`, and `outcome`, one of `pending`, `served`, `not served` or `too few probes`.

A refusal reads as a run of `403` (or `429`) records whose `head` shows the block page. An FPL
outage reads differently: `5xx` or timeouts on both targets, usually brief. Workers Logs for
`squadopt-fpl-probe` in the Cloudflare dashboard also show one `probe` line per request.

A spot check runs one live probe and prints its two records; it is context, not evidence:

```bash
curl -s -H "x-squadopt-probe: now" https://squadopt.mymandev.com/api/v1/fpl-probe/now
```

## The verdict rule, fixed before any data

**Cloudflare egress counts as served when at least 95 percent of the scheduled standings probes
in the first 72 hours from the first of them answer 200 JSON, and that window holds at least
130 of its 145 expected probes. Otherwise the forwarder is not built on Cloudflare.**

- The standings probes are the scheduled records (`trigger` `cron`) whose target is the
  standings URL. Live probes never count: a caller of `/now` chooses when and from which data
  centre they run, so they are reported apart (`summary.live`) as context. The event-status
  probes are context for reading an outage, not part of the rule.
- The window is fixed before any data: from the first scheduled standings probe to exactly 72
  hours later, both ends included, which is 145 probes at one every 30 minutes. Probes after it
  never count, so the verdict does not depend on when it is read.
- The outcome is `pending` until a scheduled standings probe exists at or after the window's
  end. Then it is final: `too few probes` when the window holds fewer than 130, otherwise
  `served` or `not served`. `too few probes` is not a verdict; the question gets a new probe.
- A probe that timed out or failed counts against the share like a refusal. Times are compared
  in whole milliseconds and the share exactly, so 152 of 160 is served and 151 of 160 is not.
- 200 JSON means HTTP status 200 with a body that parses as a JSON object or array. A 200 that
  carries an HTML challenge page is not served.

The rule is not changed after the data arrives. A different question gets a new probe with its
rule written down before it runs.

## The owner's one-time steps

The Pages token stays Pages-only ([deployment runbook](deployment_runbook.md)). The probe uses
a separate token in a separate GitHub environment. The credential rule in that runbook applies:
never paste a token into chat, a ticket, a command line or a log.

1. **Cloudflare token.** In the Cloudflare dashboard, *My Profile → API Tokens → Create Token →
   Create Custom Token*, with exactly these permissions:
   - Account → Workers Scripts → Edit
   - Account → Workers KV Storage → Edit
   - Zone → Workers Routes → Edit
   - Zone → Zone → Read

   Account resources: the one account. Zone resources: *Specific zone* `mymandev.com` only.
   Nothing else. Zone Read is read-only and is needed because wrangler, holding a token scoped
   to one zone, publishes the route through that zone and first looks its id up by name.
2. **GitHub environment.** In the repository's *Settings → Environments*, create
   `cloudflare-workers`. Under deployment branches choose *Selected branches* and allow only
   the default branch, `develop`. Add the two environment secrets; each command prompts for
   the value, so never append it:

   ```console
   gh secret set CLOUDFLARE_WORKERS_API_TOKEN --env cloudflare-workers
   gh secret set CLOUDFLARE_ACCOUNT_ID --env cloudflare-workers
   ```

3. **Deploy.** With the workflow merged to `develop`:

   ```console
   gh workflow run deploy-fpl-probe.yml --ref develop -f action=deploy
   ```

   The workflow finds or creates the KV namespace `squadopt-fpl-probe`, writes its id into
   `workers/fpl-probe/wrangler.toml` on the runner only (the committed file keeps a
   placeholder), deploys with `PROBE_UNTIL` 7 days ahead (the run's summary shows it), and asks
   `/api/v1/fpl-probe/now` once. Its log prints the first two records. A refusal by FPL in
   those records does not fail the run, because that refusal is the measurement; the run fails
   only when the Worker itself does not answer with its JSON.

   If the deploy step fails after uploading the Worker, the Worker and its schedule may already
   be live and probing without its route; it still stops at `PROBE_UNTIL`. Fix the cause, then
   deploy again, or run the delete in step 5:
   - *Could not find zone for `mymandev.com`*: the token lacks Zone → Zone → Read on
     `mymandev.com`. It is not a DNS problem; add that permission.
   - An authentication error on a `/routes` call: check the token has Zone → Workers Routes →
     Edit on `mymandev.com`. If it has, wrangler stopped before falling back from the
     account-wide route call to the zone's own, as workers-sdk pull request 15798 describes;
     run the delete in step 5 rather than widening the token to all zones.
   - Any other authentication error names the refused call; add only the permission that call
     needs.
4. **Wait** at least until `summary.verdict.outcome` is no longer `pending`, which is 72 hours
   after the first scheduled standings probe, so 3 to 4 days. The outcome is then final.
   Record it with the results JSON before deleting anything, because deleting the namespace
   deletes the records, and within 14 days of the deploy, because records expire 14 days after
   they were written and the summary would then read a later window.
5. **Delete after the probe:**

   ```console
   gh workflow run deploy-fpl-probe.yml --ref develop -f action=delete
   ```

   This deletes the Worker and its schedule first, then checks that the results path no longer
   answers as the Worker, and only then deletes the KV namespace, so a Worker that is still
   running never loses its records under it. If the check fails, the namespace is kept and the
   run fails: check *Workers & Pages* and the zone's *Workers Routes* in the dashboard. A
   second delete finds the Worker already gone, passes the check, and removes a namespace the
   first one left behind. Then, unless a forwarder is going to use them, revoke the Workers
   token in Cloudflare and remove the `cloudflare-workers` environment.

## Where it lives

| Path | What |
| --- | --- |
| `workers/fpl-probe/wrangler.toml` | Name, route, schedule, KV binding (placeholder id), observability. |
| `workers/fpl-probe/src/probe.js` | Pure rules: targets, the record, the summary and verdict, the route guard, the live probe gate, the end date. |
| `workers/fpl-probe/src/worker.js` | The scheduled and fetch handlers. |
| `workers/fpl-probe/src/index.js` | The entry point: exports the handlers and nothing else. |
| `workers/fpl-probe/scripts/deploy-steps.mjs` | The workflow's namespace lookup, id fill-in, end date, smoke and delete check. |
| `workers/fpl-probe/test/` | `node --test` suites, run by the `web (node 22)` CI job. |
| `.github/workflows/deploy-fpl-probe.yml` | Dispatch-only deploy and delete, default branch only, environment `cloudflare-workers`. |
