# ADR 0014: A usage record with no personal data, in Analytics Engine

- **Status:** proposed, for the owner's acceptance.
- **Date:** 2026-11-09
- **Decider:** the owner
- **Related:** [ADR 0004](0004-cloudflare-pages-deployment.md), [ADR 0012](0012-fpl-forwarder.md),
  [ADR 0013](0013-deadline-reminders.md), [`workers/usage`](../../../workers/usage/README.md)

## Context

Nobody can say which tools the league's members open, how many reach the member picker and leave
without taking a name, or which devices they use. The backend's API logs see only the visits that
call the backend, and the member pages are static. Cloudflare Web Analytics gives page views and
Web Vitals in the owner's dashboard, but has no custom events and cannot tell one tool from
another once the address no longer names the page's state.

The question is for any date range: pages and tools opened and how often, visits that reached the
picker against visits that took a name, language and device class, and device-side computations
started. The answer must not cost a member their privacy: no entry number, name, stored address,
cookie or fingerprint.

## Decision

1. **A third same-origin Worker, `workers/usage`, at `/api/v1/usage/*` on the site's host.** Its
   shape is the reminder's: one route prefix, no dependency, its own tests, deployed only by a
   dispatched workflow (`.github/workflows/deploy-usage.yml`). The site stays static.
2. **Pages send one small event per step, by `navigator.sendBeacon`.** `POST /api/v1/usage/events`
   takes `{page, tool, step, lang, device, session, v}` as JSON, at most 512 bytes. The beacon's
   body is a string, so the browser sends it as `text/plain` and asks no preflight.
3. **Events land in Workers Analytics Engine**, dataset `squadopt_usage`, one data point each. It
   is made for this: a write costs no round trip, the free tier takes 100 000 data points a day,
   and SQL can read a date range. KV was rejected for the reason ADR 0013 gives (1 000 writes a
   day, and daily counters cannot join a visit's steps). D1 would work but needs a row per event
   and a job to delete old rows; Analytics Engine expires them itself.
4. **The Worker refuses anything that is not the closed vocabulary.** Every field but the session
   is a word from a fixed list (`workers/usage/src/rules.js`), and the session must be sixteen
   hexadecimal characters. An address, an entry number or a name cannot be stored, whatever a page
   sends: it is refused with a 400 and not written. Extra fields are refused too.
5. **Only the site's origin is taken.** A request whose `Origin` is not
   `https://squadopt.mymandev.com` gets a 403, and CORS names no other origin. The header can be
   forged by a program that is not a browser, so this keeps other sites' pages out, not a
   determined writer; the zone's `/api/v1/` rate-limit rule stands in front of that case.
6. **The build names the one origin that may send.** A page sends only when `VITE_USAGE_ORIGIN`
   equals its own origin. With the variable empty, nothing is sent. With it set, a page on any
   other origin stays silent, so the same build served by the end-to-end suite or a preview
   address sends nothing and logs no refusal.
7. **The report is a script run by the owner**, `scripts/usage_report.mjs`, not a Worker route: a
   route would put the read token on a public address for no gain.

### What is recorded

| Field | Values | Meaning |
| --- | --- | --- |
| `page` | `entry`, `league`, `members`, `member`, `history`, `vs`, `live`, `reminder`, `team`, `fixtures`, `contribute`, `other` | The kind of page, never its address |
| `tool` | `week`, `current-squad`, `what-if`, `duel`, `chips`, `card`, `history`, `vs`, `live`, `fixtures`, or empty | What the address names on a member's page |
| `step` | `open`, `tool`, `picker_shown`, `picker_claimed`, `device_solve` | See below |
| `lang` | `tr`, `en` | The site's language |
| `device` | `phone`, `tablet`, `desktop`, `unknown` | A class from the pointer type and the screen's short side; those measurements are not sent |
| `session` | sixteen random hexadecimal characters | Joins one tab's steps; kept in `sessionStorage`, gone when the tab closes |
| `v` | `1` | The event's version |

`open` is an address the router reached. `tool` is a page drawn past its gates, so a visitor stopped
at the picker on a tool's address counts as `open` and `picker_shown`, not as using that tool.
`picker_shown` and `picker_claimed` are the member picker drawn and a name taken in it.
`device_solve` is a plan started in the visitor's browser. Analytics Engine adds the time.

### What is not recorded

No address, league number, entry number, manager or team name, query string, referrer, IP address,
user agent, screen size, country, cookie or stored identifier beyond the tab's session token. The
Worker reads none of the request's headers but `Origin` and `Content-Length`. Its invocation logs
are off, as the reminder's are, and it logs only the name of a failed write's error.

### Retention

Analytics Engine keeps data for three months and deletes it; that period is the platform's and is
not configurable. Nothing else keeps the events. A report is printed and not stored. Deleting the
Worker stops new events and leaves the rows to expire.

### How to read it

```
CLOUDFLARE_ACCOUNT_ID=... CLOUDFLARE_ANALYTICS_TOKEN=... \
  node scripts/usage_report.mjs --from 2026-11-01 --to 2026-11-30
```

The token needs the account permission `Account Analytics Read` and nothing else. The dates are
UTC days, both included. `--json` prints the same counts as JSON. A visit is one session token.

## Consequences

- The counts are a floor. A content blocker, a browser without `sendBeacon` and a request the rate
  limit stops are all silent, by design: the record never gets in a page's way.
- A visit is a tab, so a member with two tabs is two visits, and a member with a name already kept
  on their device never reaches the picker and is in neither picker count.
- A forged request from outside a browser can add false counts, though only in the vocabulary. The
  record is for product decisions and must not be read as an audit.
- Beacons count toward the zone's `/api/v1/` limit of 50 requests per 10 seconds per address. A
  page open sends two or three, far below it, and the prefix is what keeps that limit in front of
  the dataset's daily allowance.
- A new page or tool is two edits, one in the web module and one in the Worker's lists. A word the
  Worker does not know is refused, and a test in the web suite compares the two lists.
- Should the dataset ever sample under load, `SUM(_sample_interval)` keeps the event counts right
  and the session as the index keeps a visit's steps together; visit counts become approximate.
