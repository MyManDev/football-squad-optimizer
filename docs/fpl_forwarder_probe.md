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
- `GET /api/v1/fpl-probe/now` runs one live probe of both targets on request. It runs **at most
  once a minute for all callers together** (a time kept in KV); any other call in that minute
  gets `429` and asks FPL nothing. KV reaches other data centres within about a minute, so two
  callers far apart can both get a live probe in the same minute; that is the gate's slack. The
  zone's rate-limit rule on `/api/v1/` (50 requests per 10 s per IP) also stands in front of
  both paths.

The Worker answers only `GET /api/v1/fpl-probe` and `GET /api/v1/fpl-probe/now`. Every other
path under its route, and every other method, gets a `404` JSON answer. Its route is exactly
`squadopt.mymandev.com/api/v1/fpl-probe*` on the `mymandev.com` zone, it has no `workers.dev`
address, and every answer carries `cache-control: no-store`.

## What it stores, and for how long

One record per probe, in the KV namespace titled `squadopt-fpl-probe`, under
`r:<run start time, ISO>:<target index>`, **expiring after 14 days**. The namespace also holds
one key, `now:last`, the time of the last live probe, which expires after two minutes.

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
| `colo` | The Cloudflare data centre the run was in. |
| `error` | `timeout after 10000 ms`, or a short description of a network failure; `null` when an answer arrived. |

Nothing else of an answer is kept: a JSON answer leaves only its size behind, so no league
member's name or score is stored. Nothing about callers of the two paths is stored.

On the Workers Free plan KV accepts 1,000 writes a day. The schedule uses 96 of them; each live
probe uses three. A day of several hundred live probes would therefore start losing scheduled
records. A lost record shows up in the summary as a gap (`longest_gap_minutes`), so keep the
live path for spot checks.

## How to read the results

```bash
curl -s https://squadopt.mymandev.com/api/v1/fpl-probe | python -m json.tool
```

The answer holds `records` (every stored record, oldest first) and `summary`:

- `summary.targets`: per target, the number of `probes`, how many were `served` (HTTP 200 with
  a JSON body) and `served_share`, `by_status` (counts by HTTP status, with `timeout` and
  `error` for probes that got no answer), `first_at` and `last_at`, `span_hours`,
  `longest_failure_run` (`length`, `from`, `to`) and `longest_gap_minutes` between two probes.
- `summary.verdict`: the rule below applied to the standings probes, with `outcome` one of
  `pending` (less than 72 hours of them yet), `served` or `not served`.

A refusal reads as a run of `403` (or `429`) records whose `head` shows the block page. An FPL
outage reads differently: `5xx` or timeouts on both targets, usually brief. Workers Logs for
`squadopt-fpl-probe` in the Cloudflare dashboard also show one `probe` line per request.

## The verdict rule, fixed before any data

**Cloudflare egress counts as served when at least 95 percent of the standings probes over at
least 72 hours answer 200 JSON. Otherwise the forwarder is not built on Cloudflare.**

- The standings probes are every record whose target is the standings URL, scheduled and live
  together. The event-status probes are context for reading an outage, not part of the rule.
- 72 hours means from the first standings probe to the last. A probe that timed out or failed
  counts against the share like a refusal.
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

   Account resources: the one account. Zone resources: *Specific zone* `mymandev.com` only.
   Nothing else.
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
   placeholder), deploys, and asks `/api/v1/fpl-probe/now` once. Its log prints the first two
   records. A refusal by FPL in those records does not fail the run, because that refusal is the
   measurement; the run fails only when the Worker itself does not answer with its JSON. If
   the deploy step stops on an authentication error, its log names the refused call; add only
   the permission that call needs.
4. **Wait** 3 to 5 days, and at least until `summary.verdict.outcome` is no longer `pending`.
   Record the verdict with the results JSON before deleting anything, because deleting the
   namespace deletes the records.
5. **Delete after the probe:**

   ```console
   gh workflow run deploy-fpl-probe.yml --ref develop -f action=delete
   ```

   This deletes the Worker and its schedule, deletes the KV namespace, and checks that the
   results path no longer answers as the probe; if it still does, the Worker is still deployed,
   so check *Workers & Pages* and the zone's *Workers Routes* in the dashboard. A second delete
   fails at the Worker step because nothing is left; it still removes a namespace the first one
   left behind. Then, unless a forwarder is going to use them, revoke the Workers token in
   Cloudflare and remove the `cloudflare-workers` environment.

## Where it lives

| Path | What |
| --- | --- |
| `workers/fpl-probe/wrangler.toml` | Name, route, schedule, KV binding (placeholder id), observability. |
| `workers/fpl-probe/src/probe.js` | Pure rules: targets, the record, the summary, the route guard, the live probe gate. |
| `workers/fpl-probe/src/index.js` | The scheduled and fetch handlers. |
| `workers/fpl-probe/scripts/deploy-steps.mjs` | The workflow's namespace lookup, id fill-in, smoke and delete check. |
| `workers/fpl-probe/test/` | `node --test` suites, run by the `web (node 22)` CI job. |
| `.github/workflows/deploy-fpl-probe.yml` | Dispatch-only deploy and delete, default branch only, environment `cloudflare-workers`. |
