# The accumulating member record

Issue #530 adds a read-only surface on `/league`. It consumes the already published
`data/league/history/<entry>.json` through the same validator as each member's history.
Only available suggestion/actual pairs from the scoreboard's season and capture enter;
the scoreboard must also mark the week finished and checked. Missing member files and
incomplete pairs do not create zero observations. The card reports missing histories.

The observation is a member-week, grouped by gameweek. The page shows both counts, each
weekly mean and each underlying pair, with links to the member's recorded history. Its
overall mean weights member-weeks equally and is explicitly descriptive. It does not
claim that members followed the advice or that the suggestion caused the difference.
The system paper ledger never enters this series. Its legacy GW1 basis remains visible
on its own scoreboard row; the page refuses to combine different paper scoring bases.
GW1 is not rescored or rewritten by this change. It remains a separate scoring series;
missing frozen inputs are never reconstructed by assumption to make it comparable.

Both member scores use the existing history v1 scoring contract: official substitutions
and captain fallback, chip handling, and transfer costs deducted on both sides. Every
displayed pair identifies this scoring basis and the population of members who have both
a recorded suggestion and an actual score. Unsettled error cells show an em dash (—), while a
measured zero remains a zero.

## Optional measurement handoff

The research owner has not yet supplied the within-week dependence measurement. Until
then the card says that the number of further weeks is not known. The UI does not estimate
that measurement, assume an effect size, or infer a week target from the member count.
The measurement producer is owned separately in `evaluation/live_series.py`. The page
consumes its published result; the optional shape below is the current consumer seam
to align with that producer when it lands, not an implementation of the measurement.

When that measurement exists, publish `data/league/series-horizon.json` beside the
scoreboard. The standalone [member week horizon v1 contract](contracts/member_week_horizon_v1.md)
and its [JSON schema](contracts/member_week_horizon_v1.schema.json) define the required
fields, producer responsibilities and the reason within-week correlation is mandatory.

The consumer requires at least two settled week groups and an exact match of record keys,
including their captured provenance. A stale, malformed, missing or differently scoped
handoff leaves the horizon unknown. A matching handoff displays
`max(0, required_week_clusters - observed_week_clusters)`. Reaching that count does not
declare an improvement. New settled records require a refreshed measurement handoff.

No measurement artifact or made-up horizon is committed by this surface change.
