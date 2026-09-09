# Provisional gameweek score

`application.build_site` writes `data/<season>/gw<NN>/live.json` for each frozen
decision, using the same verified `CapturedSnapshot` already supplied for the
league publication. The existing `scripts.build_site` caller supplies the latest
capture; `--no-league` supplies none and therefore publishes unavailable live views.
No new upstream collection, endpoint, worker, or scheduling is involved.

The operational caller's selection is source-aware. `scripts/build_site.py` asks for
`list_snapshot_ids(root, source=FPL_LIVE_SOURCE)` and reads the last of those, which is
the newest live capture: an identifier is `{source}-{stamp}-{digest}` and the stamp is a
fixed-width rendering of `captured_at_utc`, so a lexical sort orders one source by time.
Without the filter it ordered by collector name first, and four collectors default to this
root — `fpl-live`, `fpl-top100`, `fpl-top200`, `fpl-elite-picks` — so `fpl-top200` won on
its name however old it was. A root holding no live capture passes no snapshot at all and
every live view reads unavailable; the application cannot repair a caller's selection by
mixing captures, and a missing payload is never backfilled from another one.

One selection on this path is still unfiltered: `squadopt.application.season._read_state`
lists the same root without a source for the season tick, so on a mixed root the tick
raises before the site is built. That call site belongs to the application owner and is
not changed here.

The document uses the separate, closed `live_score_v1` contract. `ui_view_v1` is
unchanged. The site includes both schemas. Older publications without `live.json`
keep rendering decisions and settled results; the provisional card says unavailable.

The application reads bootstrap, fixtures and the requested week's live payload
from that one capture. It checks payload checksums, source, season, matching frozen
deadline and capture time. The live endpoint has no embedded week: the capture's
`event-gwNN-live.json` name identifies it. Missing payloads are never backfilled or
combined with an older capture. Element IDs are resolved through that capture's
bootstrap to persistent player IDs before calling `score_named_eleven`.

The score includes the frozen captain/chip rule. The published net subtracts the
frozen transfer hit once. It does not apply automatic substitutions or vice-captain
replacement and is not labelled the official FPL total. Fixture progress and
`bonus_confirmed` come directly from `fpl_live_event_points`; confirmed bonus does
not settle a decision. No provisional value enters an outcome, league comparison,
season total, or measurement artifact.

Every displayed value is labelled as the last recorded provisional score, with its
capture ID, full date/time/timezone and publication time. A capture more than 60
minutes old additionally gets an old-capture label. This is a presentation threshold,
not a promised upstream refresh cadence. The page uses the existing query lifecycle
(mount/reconnect with a 60-second stale time; window-focus refresh is disabled by
the app), with no polling service. A
document regenerated from an old capture remains old. A settled decision hides the
card; a later site build replaces its live document with `unavailable/settled`.

Validation covers chip/hit arithmetic, identity and missing-source refusals, the
separate schema, byte-for-byte ledger preservation through site generation,
replacing an old available document, and the existing settled page. Synthetic
previews are labelled explicitly and do not publish real season scores.
