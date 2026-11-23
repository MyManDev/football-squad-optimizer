# ADR 0016: The usage record read inside the site, behind Cloudflare Access

- **Status:** accepted by the owner on 2026-11-16.
- **Date:** 2026-11-16
- **Decider:** the owner
- **Related:** [ADR 0014](0014-usage-measurement.md), [ADR 0015](0015-behaviour-measurement.md),
  [`workers/usage`](../../../workers/usage/README.md)

## Context

ADR 0014 kept the report out of the Worker: a report route would have put the read token on a
public address. The owner now wants the record read on the site itself, in two places: an admin
page with the whole report, and a heatmap drawn over the live page a person is looking at. Both
need the aggregated counts in a browser, for a few named people and nobody else.

## Decision

1. **Cloudflare Access guards two paths of the site's host:** `/admin/*` (the page) and
   `/api/v1/usage/report*` (the data), in one Access application, so one sign-in opens both.
   The allowed people are an email list kept in the Access policy, never in this repository.
2. **The usage Worker serves the report.** `GET /api/v1/usage/report?from=YYYY-MM-DD&to=YYYY-MM-DD`
   answers the JSON `scripts/usage_report.mjs --json` prints, for at most 92 UTC days ending no
   later than today; `GET /api/v1/usage/report/me` answers `{"contract_version":"usage_admin_v1",
   "admin":true}` and reads nothing. The report's queries and arithmetic move into one module,
   `workers/usage/src/report.js`, that the Worker and the script both use, so the two cannot
   count differently.
3. **The Worker checks the sign-in itself.** Both routes require the `Cf-Access-Jwt-Assertion`
   header: an RS256 token signed by a key of the team's
   `https://<team>.cloudflareaccess.com/cdn-cgi/access/certs`, whose `aud` names the application's
   audience tag and whose `iss`, `exp` and `nbf` hold. Without it, or with a token that fails any
   check, the answer is 403 and nothing is read; a misconfigured or missing Access application
   therefore exposes nothing. Without the Worker's settings (`ACCESS_TEAM_DOMAIN`, `ACCESS_AUD`,
   `ANALYTICS_ACCOUNT_ID`, `ANALYTICS_TOKEN`) both routes answer 503 `report_not_configured`.
4. **The read token is a Worker secret.** `ANALYTICS_TOKEN` holds a token with the account
   permission `Account Analytics Read` and nothing else. The deploy workflow writes it from the
   `cloudflare-workers` environment's secret `USAGE_READ_TOKEN`, and the two Access values from the
   environment's variables `ACCESS_TEAM_DOMAIN` and `ACCESS_AUD`; a deploy without them still
   deploys and leaves the report unconfigured.
5. **The admin page** is the route `/admin/usage`, a lazy chunk the public pages never load. It
   draws the report for a chosen range (today, 7 days, 28 days, or two dates) with the same
   sections as the owner's dashboard: totals, the funnel, tools and pages, sources and returns,
   scroll, speed, errors, and per page and device the clicks by zone.
6. **The heatmap mode** draws the report's clicks over the live page. A browser that has opened
   the admin page successfully keeps `squadopt.admin = 1` in `localStorage`; only such a browser
   asks `/report/me`, and only on a 200 does a small button appear. Pressed, it draws every
   `data-zone` element's 20 by 20 cells over its current box, for the page the address names, a
   chosen device class and mark, and redraws on scroll, resize and layout changes. Every other
   visitor sends no extra request and loads none of its code.
   Amended on 2026-11-23: the mode draws only the clicks whose page and tool both match the
   address, since every member tool shares the page `member`, and never draws zone `page`,
   whose whole-document grid moves with the page's length; it counts those clicks instead.
7. **Admins are not counted.** A browser with `squadopt.admin = 1` sends no usage event of either
   version, so the people reading the record do not move it.

## Consequences

- One more secret lives in Cloudflare and one more in GitHub. The token can only read analytics.
- The report reads Analytics Engine on each request; a person opening the page a few times a day
  is far inside the SQL API's limits, and nothing is cached in a browser beyond the page's life.
- A layout change moves zones, and the heatmap mode follows it because it draws on the live boxes;
  the counts of a range that spans the change mix the two layouts.
- Clearing site data on an admin's browser makes it a counted visitor again until the admin page
  is opened once more.
