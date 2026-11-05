# FPL forwarder Worker

A Cloudflare Worker at `squadopt.mymandev.com/api/v1/fpl/*` that reads the Fantasy Premier League
API on a visitor's request and answers with trimmed, versioned documents, so the site's own pages
can read any classic league, any entry and the live week. It never answers with FPL's own JSON.
The decision, its cache rules and its terms note are
[ADR 0012](../../docs/architecture/decisions/0012-fpl-forwarder.md).

## Routes

| Route | Answers |
| --- | --- |
| `GET /api/v1/fpl/standings/{league}?page={1..20}` | [`fpl_league_standings_v1`](../../docs/contracts/fpl_league_standings_v1.md) |
| `GET /api/v1/fpl/entry/{entry}/bundle?gw={table gameweek}` | [`fpl_entry_bundle_v1`](../../docs/contracts/fpl_entry_bundle_v1.md) |
| `GET /api/v1/fpl/live/{gameweek}` | [`week_live_v1`](../../docs/contracts/week_live_v1.md), without member blocks |

Every other path answers a JSON 404, and another method on these paths a JSON 405. Every answer
is JSON and carries `x-squadopt-fpl: 1`; a document also carries `x-squadopt-fpl-cache`, which
says `miss` (read from FPL just now), `hit` (this data centre's copy) or `last-good` (FPL refused
or failed, and the last good copy is served with its original `source_time`).

## Layout

| Path | What |
| --- | --- |
| `wrangler.toml` | Name, the one route, no `workers.dev` and no preview addresses, logs without per-request invocation logs |
| `src/index.js` | The entry point; it exports the handler and nothing else |
| `src/worker.js` | The fetch handler: FPL, the site's fixture list and the Cache API |
| `src/proxy.js` | Pure rules: the allowlist, the trimming, the schedule, the member week and the copies' lifetimes |
| `scripts/deploy-steps.mjs` | The workflow steps written as JavaScript: the smoke and the delete check |
| `test/` | `node --test` suites, with synthetic FPL-shaped answers (`support.mjs`) and a small JSON Schema reader (`schema.mjs`) |

## Running it

- **Tests** run in the `FPL forwarder worker tests` step of the CI web job, from the repository
  root, with no credentials and no network:

  ```sh
  node --test workers/fpl-proxy/test/proxy.test.mjs workers/fpl-proxy/test/worker.test.mjs workers/fpl-proxy/test/deploy-steps.test.mjs
  ```

- **Deployment and deletion** happen only through `.github/workflows/deploy-fpl-proxy.yml`,
  dispatched by hand from the default branch into the `cloudflare-workers` environment. Its
  smoke asks `/api/v1/fpl/smoke`, which is none of the routes, so it asks FPL nothing. The Pages
  token and the Pages site are never touched.
- **State**: none of its own. Copies live in each data centre's Cache API and expire by
  themselves; there is no KV namespace, no cron and no secret in the Worker.

Issue #980 tracks the forwarder; #983 and #1008 build the site's readers on it.
