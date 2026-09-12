# Scoreboard comparisons v1

This additive extension belongs to each `payload.gameweeks[]` object in the
`provisional_league_ui_v1` scoreboard. The existing scoreboard fields keep their
meaning. Older publications without `comparisons` remain readable.

Validate each gameweek with [the extension schema](scoreboard_comparisons_v1.schema.json).
The schema requires exactly six rows in this order:

| Kind | Source and meaning |
| --- | --- |
| `system` | Frozen season ledger decision, net of its recorded transfer charge. |
| `base` | Reserved for the base component provider. Null in this release. |
| `elite_xi` | Reserved for the lagged elite squad provider. Null in this release. |
| `ownership_template` | Reserved for the ownership template provider. Null in this release. |
| `league_mean` | Mean member net points from captured entry histories, with the existing coverage counts. |
| `game_mean` | FPL's published average, on its source basis. It is not relabelled as member net. |

Each row has `kind`, nullable `net`, nullable `scoring_basis`, nullable
`source_snapshot_id`, and `diagnostics`. Reserved rows do not manufacture decisions
or scores. The baseline providers are a separate change.

## Measurements

All four diagnostic keys are present. Missing evidence is JSON `null`, never a
measured zero. The web table shows missing measurements as `-` in both languages.

| Diagnostic | Definition |
| --- | --- |
| `zero_minute_starters` | Count of the frozen eleven with exactly zero settled minutes; an integer from 0 to 11. |
| `minutes_shortfall` | Sum of projected minus settled minutes over frozen starters who played. Null when any required prediction is absent or invalid. |
| `captain_shortfall` | Frozen captain's expected points minus the ordinary captain bonus received, including recorded vice recovery. Null without that prediction. |
| `autosub_recovery` | Substitute points returned by the existing official scorer. Null when no recorded bench order and vice are available. |

Residuals are signed. A negative shortfall means the observation exceeded the
prediction. The extra Triple Captain copy is outside the captain diagnostic;
Bench Boost includes all fifteen players and has zero autosub recovery. These are
settlement rules, not chip recommendations.

Comparison scores and diagnostics are null until both `finished` and
`data_checked` are true. League and game averages have no player diagnostics.

## Scoring and provenance

Legacy decisions retain `named_eleven_no_autosubs`: their named eleven and captain
are scored without inventing a bench order or vice. Decisions with explicitly
recorded bench order and vice use `official_autosub_captain_v2`, the existing
validated scorer. The `ours` row additionally exposes the same diagnostics and
`outcome_snapshot_id`; `vice_captain_named` describes the frozen decision.

The publication reads verified ledger entries and event-live captures. The archive
is scanned once, retaining at most one capture per requested gameweek. Settlement
uses the latest checked, finished capture from the same season, after that week's
deadline and no later than the publication capture. Ties use the snapshot ID.
The selected capture ID travels with the outcome. If no eligible capture exists,
the recorded outcome is retained; without either, the result stays null.

Scoring uses frozen projections and persistent player codes, and creates derived
outcomes in memory. It never writes ledger decisions, outcomes, or manifests.
Missing settled player coverage, invalid identities and non-finite observations
refuse publication instead of inventing values. Input failures occur before the
existing published file is replaced.

When the ledger root is empty, the existing same-season published `ours` rows
remain available under the publication retention rule. This does not reconstruct
missing decisions, captures or capture-time eligibility. No scoreboard data file
is committed by this change; the normal weekly publication produces it.
