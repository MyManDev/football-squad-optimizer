# Weekly suggestion evaluation

The first version compares a member's recorded one-week pure-points suggestion with
their actual weekly result. It is limited to league **352490**. The implementation is
on `feat/weekly-suggestion-eval`, based on enterprise review commit `4b55253f`.

## Evidence and selection

- Read existing member advice through the manifest-verifying archive reader.
- Select `saf-puan`, window `1`, without a rival. Order eligible records by their
  recorded publication time, not capture time. Both clocks must precede the deadline;
  equality with the deadline is too late. Publication cannot precede capture.
- Reject ambiguous or corrupt evidence instead of substituting an older result.
- Show only weeks with an actual member record directory. An empty archive is an
  empty history; no earlier recommendations are reconstructed or solved again.
- The archive records publisher output. It does not establish that a member viewed
  the page, followed the suggestion, or obtained a causal benefit from it.

## Scoring and interpretation

`application/weekly_suggestion_eval.py` uses the existing frozen-squad scorer for
formation-preserving automatic substitutions and captain fallback. The wrapper applies
recorded transfer costs and known Bench Boost / Triple Captain adjustments. Wildcard
and Free Hit must have no transfer charge. Unknown chips or incomplete lineups are
reported as unavailable.

A week must be both `finished` and `data_checked` in the captured bootstrap. Player
outcomes are joined through persistent FPL element codes. Result captures are bounded
by the publication's named input snapshot, so a newer capture on disk cannot supply
future outcomes to an older publication.

The actual member score comes from that outcome capture's exact weekly history row:
gross points minus its recorded transfer charge. A missing charge is unknown, never
zero. A known suggested result can still be displayed when the member's actual result
is absent; the comparison then stays unknown.

The signed difference is **suggested net minus actual net**. Player rows show recorded
expected points, actual unmultiplied points, their difference, minutes, recorded role,
captain/vice, scoring multiplier and counted contribution. The recorded aggregate
expectation is XI plus captain, before transfer costs and extra chip points; the UI
explicitly distinguishes this from a net forecast. No accuracy percentage is inferred.

## Publication and UI

The existing league publisher writes derived JSON under
`data/league/history/{entry_id}.json` with contract `weekly_suggestion_history_v1`.
`history_record_root` allows preview runs to read existing records without writing
new private advice records. Normal weekly publication supplies the same configured
record root. This adds no API, solver job, model, scheduler or infrastructure service.

The member page links to `/league/members/{entry_id}/history`. The Turkish/English
page provides a recorded-week selector, score comparison, player details and expandable
source timestamps/digests. Missing files, unfinished results and unreadable records
have distinct states. Its loader never falls back to example data.

`generated_at_utc` in this derived contract denotes the input capture cutoff for
outcomes, shown as the result-data date. The original advice publication timestamp
remains separate and can be later than its input capture.

## Verification and current data

Verified locally on 10 September 2026:

- 106 focused Python tests: selection, scoring, source identity, exact Python/browser
  fixture agreement, installed publication, weekly operations and publication CLIs.
- Full web unit suite: 512 passed, 2 existing opt-in tests skipped.
- Two Chromium acceptance tests: member navigation, mobile layout, player breakdown,
  source details, reload, missing/unsettled/invalid states; no axe violations.
- Ruff, strict mypy (259 source files), both import-layer contracts, web lint,
  formatting, type checking, production build and deployment-asset validation passed.
- Initial JavaScript: 142.4 kB gzip against the existing 150 kB budget.

The local private archive contains 15 members with **GW4 only**. All 15 correctly
produce `unsettled` using capture `fpl-live-20260909T055021Z-94238cf346c5`.
Before/after SHA-256 inventories of 477 source files were identical. A real GW4
history was opened in Chromium from the production bundle with no page errors and no
invented score. Settled-score acceptance uses explicitly synthetic evidence because
the real archive has no settled recommendation week yet.

Raw records, captures, local audit inventories and screenshots remain ignored.
The enterprise review checkout is unchanged. This feature has not been deployed to
production; the real-data browser verification is a local preview.
