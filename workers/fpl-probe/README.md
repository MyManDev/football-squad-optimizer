# FPL probe Worker

A low-rate Cloudflare Worker that measures whether the Fantasy Premier League API answers
requests leaving Cloudflare's network. It forwards nothing to anyone; it answers only with its
own records. The measurement, its verdict rule and the owner's one-time steps are in
[the FPL forwarder probe](../../docs/fpl_forwarder_probe.md).

## Layout

| Path | What |
| --- | --- |
| `wrangler.toml` | Name, route, cron schedule and the KV binding, whose namespace id is a placeholder the workflow fills in |
| `src/index.js` | The entry point; it exports the handlers and nothing else |
| `src/worker.js` | The scheduled and fetch handlers |
| `src/probe.js` | Pure rules: targets, the record, the summary and verdict, the route guard, the live-probe gate and the end date |
| `scripts/deploy-steps.mjs` | The workflow steps written as JavaScript: the namespace lookup, the id fill-in, the end date, the smoke check and the delete check |
| `test/` | `node --test` suites for the rules and the deployment steps |

## Running it

- **Tests** run in the `FPL probe worker tests` step of the CI web job, from the repository
  root:

  ```sh
  node --test workers/fpl-probe/test/probe.test.mjs workers/fpl-probe/test/deploy-steps.test.mjs
  ```

- **Deployment and deletion** happen only through `.github/workflows/deploy-fpl-probe.yml`,
  dispatched by hand from the default branch into the `cloudflare-workers` environment. The
  Pages token and the Pages site are never touched.
- **Schedule**: every 30 minutes the Worker asks each of its two FPL targets once, until the end
  date the workflow sets at deployment; without that date it asks FPL nothing.
- **Records** are kept in the KV namespace titled `squadopt-fpl-probe` and expire after 14 days.

Issue #979 tracks the token, the environment and the measurement run. The forwarder the probe
qualifies is issue #980.
