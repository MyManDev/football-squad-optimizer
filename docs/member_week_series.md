# The accumulating member record

No page reads this record since the `/league` card was removed, so a stale horizon file
changes nothing a member sees. The weekly run still measures it, and
`data/leagues/<league id>/series-horizon.json` stays published under the publication identity
(`docs/contracts/league_publication_identity_v1.md`). Each member's own weeks are on their
history page, read from `data/leagues/<league id>/history/<entry>.json`.

Only settled suggestion/actual pairs enter. Unsettled and refused weeks, and settled weeks
whose actual score is unknown, do not create zero observations.

The observation is a member-week, grouped by gameweek. The record does not claim that
members followed the advice or that the suggestion caused the difference.
The system paper ledger never enters this series. Its legacy GW1 basis stays on its own row
of `scoreboard.json`, and the producer totals only weeks on the series basis.
GW1 is not rescored or rewritten. It remains a separate scoring series;
missing frozen inputs are never reconstructed by assumption to make it comparable.

Both member scores use the existing history v1 scoring contract: official substitutions
and captain fallback, chip handling, and transfer costs deducted on both sides. The document
names this scoring basis and the population of members who have both a recorded suggestion
and an actual score.

## Measurement handoff

`evaluation/live_series.py` estimates the within-week dependence, and
`application/weekly_suggestion_eval.py` writes `series-horizon.json` beside the scoreboard, or
removes an earlier one when the record supports no horizon. The standalone
[member week horizon v1 contract](contracts/member_week_horizon_v1.md) and its
[JSON schema](contracts/member_week_horizon_v1.schema.json) define the required fields,
producer responsibilities and the reason within-week correlation is mandatory.

Reaching the target count does not declare an improvement. New settled records require a
refreshed document.
