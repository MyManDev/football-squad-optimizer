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
no position, message or address can be stored. The report counts both versions; its query and
arithmetic live in `src/report.js`, which the script and the Worker's report route both use, and
the shape of its JSON is described at the top of that module.

The record is also read inside the site, by the people a Cloudflare Access policy names
([ADR 0016](../../docs/architecture/decisions/0016-usage-admin-views.md)): an admin page and a
heatmap over the live page, both fed by the two report routes below.

| Route | Method | Answer |
| --- | --- | --- |
| `/api/v1/usage/events` | `POST`, from the site's origin only | `204`, or `400` naming the first thing wrong, `403` for another origin, `503` when the dataset fails |
| `/api/v1/usage/status` | `GET` | Whether the Worker is bound to its dataset, and the event versions it takes; the deploy's smoke reads it and writes nothing |
| `/api/v1/usage/report?from=YYYY-MM-DD&to=YYYY-MM-DD` | `GET`, signed in through Access | `200` with the JSON `scripts/usage_report.mjs --json` prints, for UTC days both included, at most 92 of them, ending today at the latest; `400` naming what is wrong with the range (`from_not_a_date`, `to_not_a_date`, `from_after_to`, `to_in_future`, `range_too_long`); `502` `analytics_unavailable` when Analytics Engine fails |
| `/api/v1/usage/report/me` | `GET`, signed in through Access | `200` `{"contract_version":"usage_admin_v1","admin":true}`; reads nothing. The site's heatmap button asks it first |

Both report routes answer `403` `access_refused` without a valid Access token and `503`
`report_not_configured` without the four settings below, read nothing in either case, and answer
with `cache-control: private, no-store` and no CORS header (the admin page is on the same origin).
Any other method is `405`.

### The report's settings

Four Worker secrets, written by the deploy workflow after each deploy:

| Worker secret | From the `cloudflare-workers` environment | What it is |
| --- | --- | --- |
| `ANALYTICS_TOKEN` | secret `USAGE_READ_TOKEN` | A Cloudflare API token with the account permission `Account Analytics Read` and nothing else |
| `ANALYTICS_ACCOUNT_ID` | secret `CLOUDFLARE_ACCOUNT_ID` | The account whose Analytics Engine holds the dataset |
| `ACCESS_TEAM_DOMAIN` | variable `ACCESS_TEAM_DOMAIN` | The Access team's host, such as `squadopt.cloudflareaccess.com` (`https://` and a trailing slash are accepted) |
| `ACCESS_AUD` | variable `ACCESS_AUD` | The Access application's audience tag |

If `USAGE_READ_TOKEN` or either variable is empty, the deploy writes none of the four, says so in a
notice and still deploys; the report routes then answer `503`.

The Worker checks the `Cf-Access-Jwt-Assertion` header itself, so a missing or misconfigured Access
application exposes nothing: the token must be RS256, signed by a key from
`https://<team>/cdn-cgi/access/certs` (kept in memory for ten minutes and read once more for a key
it does not know), with `aud` naming `ACCESS_AUD`, `iss` equal to `https://<team>`, and `exp`,
`nbf` and `iat` holding with 60 seconds of clock skew. It logs only which check failed, never the
token, an email or the read token.

## Deploying

1. Dispatch `.github/workflows/deploy-usage.yml` from the default branch with `deploy`. It uses the
   `cloudflare-workers` environment's existing `CLOUDFLARE_WORKERS_API_TOKEN` and
   `CLOUDFLARE_ACCOUNT_ID`. The dataset is created by its first write.
2. If wrangler refuses the deploy saying Analytics Engine is not enabled, open Workers & Pages,
   Analytics Engine, in the Cloudflare dashboard, enable it once and dispatch again.
3. Set the repository variable `USAGE_ORIGIN` to `https://squadopt.mymandev.com`. The next site
   build reads it as `VITE_USAGE_ORIGIN`; until then the site sends nothing.

### Access

1. In Zero Trust, Access, Applications, add one self-hosted application with two destinations on
   `squadopt.mymandev.com`: the path `admin/*` (the page) and the path `api/v1/usage/report*`
   (the data). One sign-in then opens both.
2. Give it one Allow policy whose rule is `Emails` with the admins' addresses. The list lives in
   the policy, never in this repository.
3. Copy the application's audience (AUD) tag into the `cloudflare-workers` environment's variable
   `ACCESS_AUD`, the team's host into `ACCESS_TEAM_DOMAIN`, and the read-only token into its
   secret `USAGE_READ_TOKEN`, then dispatch the deploy.

## Reading

Create a Cloudflare API token with the account permission `Account Analytics Read`, then:

```
CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_ANALYTICS_TOKEN=... \
  node scripts/usage_report.mjs --from 2026-11-01 --to 2026-11-30
```

## Testing

`node --test` with the files the `Usage worker tests` step of `ci.yml` names: a fake dataset,
handed-in rows, and for the report routes a signing key made in the test with a fake Access key
set and SQL API behind a handed-in fetch. No credentials and no network.
