# ADR 0015: Clicks, scroll, speed, errors and arrivals in the usage record, still with no personal data

- **Status:** accepted by the owner on 2026-11-16.
- **Date:** 2026-11-16
- **Decider:** the owner
- **Related:** [ADR 0014](0014-usage-measurement.md), [`workers/usage`](../../../workers/usage/README.md)

## Context

ADR 0014 counts the pages and tools a visit opens and the member picker's two steps. It cannot say
where on a page members tap, how far down they read, which taps do nothing or are repeated in
frustration, how fast pages are on their devices, which errors they meet, where they came from, or
whether they come back the next week. Hosted tools answer those with a third-party script, cookies
and session recordings, which would need a consent banner and send members' behaviour to another
company. The owner asked for the same questions answered under ADR 0014's rule instead.

## Decision

1. **Version 2 events beside version 1, in the same Worker, route and dataset.** Version 1 stays
   exactly as ADR 0014 describes it. A version 2 event has `v: 2`, a `kind`, the six common fields
   of version 1 except `step` (`page`, `tool`, `lang`, `device`, `session`), and the fields of its
   kind, nothing else. Every text field is a word from a closed list in
   `workers/usage/src/rules.js`; every number is an integer in a fixed range. The 512-byte limit,
   the origin rule and the rate-limit rule of ADR 0014 apply unchanged.
2. **No component sends anything itself.** One module in the site listens at the document for
   clicks, scrolling, page hide, errors and the browser's performance entries, and turns them into
   events. Components only carry a `data-zone` attribute whose value is a word of the zone list.
3. **The heatmap is by zone, not by pixel.** A click names the nearest ancestor with a known
   `data-zone` (or `page` when there is none) and the cell of a 20 by 20 grid over that element's
   box where it landed. For `page` the grid is over the whole document. A report draws the cells
   over a screenshot of the zone, taken at a phone and a desktop width.
4. **Coming back is a bucket worked out in the browser.** The browser keeps one value, the ISO week
   of the last visit (`squadopt.usage.week` in `localStorage`), and sends only which bucket this
   visit is in. No identifier outlives the tab.
5. **Where a visit came from is a word worked out in the browser.** The referrer's host and a
   `utm_source` are matched against a fixed list; the address itself is never sent.
6. **The report reads both versions.** `scripts/usage_report.mjs` keeps its version 1 tables and
   adds the version 2 ones, and `--json` prints everything the owner's dashboard draws.

### Common fields

`page` and `tool` as ADR 0014, with `llmopt` added to both lists (the constrained planner's page,
which version 1 counted as `other`). `lang`, `device` and `session` as ADR 0014.

### Kinds

| `kind` | Fields | Values | When |
| --- | --- | --- | --- |
| `click` | `zone`, `cell`, `target`, `mark` | `zone` from the zone list; `cell` 0 to 399 (row times 20 plus column); `target` `control` or `plain`; `mark` `none`, `rage` or `dead` | Half a second after a click, at most one a quarter second and 150 a page view |
| `scroll` | `depth`, `dwell` | `depth` 0 to 100 in steps of 10, the deepest share of the page seen; `dwell` `s5`, `s15`, `s30`, `s60`, `s180`, `s600`, `long` | Once a page view: on the next address, on page hide or when the tab is hidden |
| `vital` | `metric`, `rating`, `value` | `metric` `lcp`, `inp`, `cls`, `fcp`, `ttfb`; `rating` `good`, `needs`, `poor`; `value` 0 to 60000 (milliseconds, or layout shift times 1000) | As the browser reports each, once a page load |
| `error` | `error` | `script`, `promise`, `chunk` | On an uncaught error or rejection, at most 5 a page view and one of each kind a second |
| `arrival` | `source`, `visit` | `source` `direct`, `internal`, `whatsapp`, `telegram`, `google`, `bing`, `x`, `instagram`, `facebook`, `reddit`, `fpl`, `other`; `visit` `new`, `same_week`, `last_week`, `weeks_2_4`, `older`, `unknown` | Once a tab, with its first page |

- A click is a `control` when its target is inside a link, a button, a form field, a `summary`, a
  `label` or an element whose role is `button`, `link`, `tab`, `switch`, `checkbox`, `radio`,
  `menuitem` or `option`.
- `rage` is the third click within 800 milliseconds inside 30 pixels of the first; one `rage`
  event stands for the burst, and the burst's other clicks send nothing.
- `dead` is a click after which, for half a second, the document did not change and the address
  did not move.
- `chunk` is a script or module that failed to load (a stale deployment); `script` any other
  uncaught error; `promise` an unhandled rejection. Messages and stacks are never sent.

### Zones

`nav`, `topbar`, `entry-form`, `league-list`, `fpl-id-help`, `member-table`, `member-picker`,
`decision`, `pitch`, `squad`, `fixtures-rail`, `tool-tabs`, `chip-timing`, `chip-choice`,
`preferences`, `advice-request`, `advice-details`, `what-if`, `duel`, `last-week`, `apply-fpl`,
`resources`, `coach-news`, `new-information`, `history`, `vs`, `live`, `llmopt`, `reminder`,
`fixtures`, `contribute`, `page`. A word missing from a component is `page`; a word the Worker
does not know is refused, and a test in the web suite compares the two lists as it does for pages
and tools.

### The dataset's columns

`blob1` to `blob6` keep version 1's meaning (`page`, `tool`, `step`, `lang`, `device`,
`session`); a version 2 event puts its `kind` in `blob3`. `blob7` to `blob9` and `double2` carry
the kind's fields: `click` `zone`, `target`, `mark` and `cell`; `scroll` `dwell` and `depth`;
`vital` `metric`, `rating` and `value`; `error` `error`; `arrival` `source` and `visit`. `double1`
is the version. The session stays the index.

### What is still not recorded

Everything ADR 0014 lists, and also: pixel positions, element text or names, form contents,
error messages and stacks, the referrer's address, any `utm_` value outside the source list, and
the timestamps behind a dwell bucket.

## Consequences

- A page view sends about twenty events instead of two or three. A busy day of the league stays far
  below the free tier's 100 000 data points, and the throttles keep a visitor below the zone's
  `/api/v1/` limit of 50 requests in 10 seconds.
- Zones follow the components that carry them. A component without one counts as `page`, so the
  heatmap degrades to the page grid rather than breaking.
- A layout that changes between two weeks moves the cells under the same zone. A report reads one
  date range against one screenshot, taken from the site of that range.
- `localStorage` holds one week string per browser. It is never sent and identifies no one; clearing
  the site's data makes the next visit `new`.
- The counts stay a floor, for ADR 0014's reasons.
