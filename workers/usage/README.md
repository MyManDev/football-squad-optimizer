# Usage record

Takes one small event per step of a visit and writes it to Workers Analytics Engine, so that a
report can say which pages and tools members open, how many take a name in the member picker,
their language and device class, and how many plans their browsers start. It records no personal
data. [ADR 0014](../../docs/architecture/decisions/0014-usage-measurement.md) is the decision and
lists exactly what is and is not recorded.

Version 2 events ([ADR 0015](../../docs/architecture/decisions/0015-behaviour-measurement.md)) go
to the same route and dataset beside version 1, which is unchanged. Each has a `kind`: a
`click` names its zone of the page, a cell of a 20 by 20 grid over it, whether it hit a control
and whether it was a rage or dead click; a `scroll` the deepest tenth of the page seen and a time
bucket; a `vital` a speed metric, its rating and its value; an `error` only its kind; an
`arrival` where the visit came from and how long since the last one, as words. Every text field
is a word from a closed list in `src/rules.js` and every number an integer in a fixed range, so
no position, message or address can be stored. The report prints both versions, and its
`--json` shape is described at the top of `scripts/usage_report.mjs`.

| Route | Method | Answer |
| --- | --- | --- |
| `/api/v1/usage/events` | `POST`, from the site's origin only | `204`, or `400` naming the first thing wrong, `403` for another origin, `503` when the dataset fails |
| `/api/v1/usage/status` | `GET` | Whether the Worker is bound to its dataset, and the event versions it takes; the deploy's smoke reads it and writes nothing |

## Deploying

1. Dispatch `.github/workflows/deploy-usage.yml` from the default branch with `deploy`. It uses the
   `cloudflare-workers` environment's existing `CLOUDFLARE_WORKERS_API_TOKEN` and
   `CLOUDFLARE_ACCOUNT_ID`. The dataset is created by its first write.
2. If wrangler refuses the deploy saying Analytics Engine is not enabled, open Workers & Pages,
   Analytics Engine, in the Cloudflare dashboard, enable it once and dispatch again.
3. Set the repository variable `USAGE_ORIGIN` to `https://squadopt.mymandev.com`. The next site
   build reads it as `VITE_USAGE_ORIGIN`; until then the site sends nothing.

## Reading

Create a Cloudflare API token with the account permission `Account Analytics Read`, then:

```
CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_ANALYTICS_TOKEN=... \
  node scripts/usage_report.mjs --from 2026-11-01 --to 2026-11-30
```

## Testing

`node --test` with the four files the `Usage worker tests` step of `ci.yml` names: a fake dataset
and handed-in rows, no credentials and no network.
