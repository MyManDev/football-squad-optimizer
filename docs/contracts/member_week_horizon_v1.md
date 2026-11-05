# Member week horizon v1

This optional publication lives at `data/leagues/<league id>/series-horizon.json`, beside the
scoreboard. It is a standalone JSON object, not a `provisional_league_ui_v1`
envelope. Validate it with [the schema](member_week_horizon_v1.schema.json).
The Python measurement producer owns the estimate. No page reads this document since the
`/league` card was removed; it stays published under the publication identity
(`docs/contracts/league_publication_identity_v1.md`).

## Fields

All fields below are required when a horizon document is published. The file itself
may be absent until a measurement is available. There is no zero-valued or null-valued
substitute for an unavailable estimate.

| Field | Meaning |
| --- | --- |
| `contract_version` | Exactly `member_week_horizon_v1`. |
| `season`, `league_id` | The scoreboard's season and league identity. |
| `scoring_basis` | Exactly `official_autosub_captain_v2`. |
| `population` | Exactly `recorded_member_suggestions_vs_actual`; the paper ledger is excluded. |
| `measurement_artifact` | `docs/<slug>.json`, naming a committed measurement with an entry in the measurements index. The artifact records the target effect, method, inputs and dependence estimate. |
| `within_week_correlation` | Finite measured dependence between member observations within a week, from -1 to 1 inclusive. Required even though it is not displayed. |
| `required_week_clusters` | The measured total number of weekly groups required, an integer of at least two, not the number of additional weeks. |
| `member_week_keys` | Unique record keys for exactly the evaluated member-week pairs: `<entry id>:<gameweek>:<advice sha256>:<outcome snapshot id>`. Order is immaterial. |

## Why dependence is required

Members in the same gameweek share conditions. Counting them as independent weeks
would make a week target appear supported by more independent evidence than exists.
`within_week_correlation` is therefore a required declaration that the measurement
records this dependence. It must come from the same measurement and record population
as the week target; the producer must not insert zero merely to satisfy validation.

The schema checks its presence, finiteness and range. This structural check cannot prove
the validity of the measurement method: that evidence belongs in `measurement_artifact`.
An omitted, null or invalid correlation leaves the horizon unknown. If dependence
cannot be measured, do not publish a numeric target for this contract.

## Context checks beyond the schema

No page makes these checks today; whatever reads this document next has to. It first
builds the member series from available suggestion/actual history pairs in the scoreboard's
season and capture. A week must be finished and checked.
Missing histories and incomplete pairs contribute no observations, never zeros.

There must be at least two distinct settled gameweeks. `season`, `league_id`, basis
and population must match, and `member_week_keys` must equal the complete current
series keys, including advice and outcome provenance. A schema-valid document for
another series is still rejected. New settled records require a refreshed measurement.
The producer must verify the artifact and its evidence before publishing; nothing after
it fetches or authenticates the referenced file.

Only after these checks are the weeks still to run
`max(0, required_week_clusters - observed_week_clusters)`. Zero means the recorded
week target has been reached; it does not establish an improvement. A missing,
malformed, stale or differently scoped file means the required weeks are unknown.

See [the member-series guide](../member_week_series.md) for the population
and [the comparison contract](scoreboard_comparisons_v1.md) for the separate paper ledger.
