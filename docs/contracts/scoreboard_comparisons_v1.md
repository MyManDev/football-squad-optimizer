# Scoreboard comparisons v1

This additive extension belongs to each `payload.gameweeks[]` object in the
`provisional_league_ui_v1` scoreboard. The existing scoreboard fields keep their
meaning. Older publications without `comparisons` remain readable.

Validate each gameweek with [the extension schema](scoreboard_comparisons_v1.schema.json).
The schema requires exactly six rows in this order:

| Kind | Source and meaning |
| --- | --- |
| `system` | Frozen season ledger decision, net of its recorded transfer charge. |
| `base` | Frozen component-only decision paired to the system capture, supplied by `--baseline-ledger-root`. |
| `elite_xi` | Synthetic legal squad using complete lagged Top-100 starter counts and captain counts. |
| `ownership_template` | Synthetic legal squad using captured ownership. |
| `league_mean` | Mean member net points from captured entry histories, with the existing coverage counts. |
| `game_mean` | FPL's published average, on its source basis. It is not relabelled as member net. |

Each row has `kind`, nullable `net`, nullable `scoring_basis`, nullable
`source_snapshot_id`, and `diagnostics`. Missing sources leave rows empty; no
historical source is reconstructed.

## Measurements

All four diagnostic keys are present. Missing evidence is JSON `null`, never a
measured zero. The web table shows missing measurements as `-` in both languages.

| Diagnostic | Definition |
| --- | --- |
| `zero_minute_starters` | Count of the frozen eleven with exactly zero settled minutes; an integer from 0 to 11. |
| `minutes_shortfall` | Sum of projected minus settled minutes over frozen starters who played. Null when any required prediction is absent or invalid. |
| `captain_shortfall` | Frozen captain's expected points minus the ordinary captain bonus received, including recorded vice recovery. Null without that prediction. |
| `autosub_recovery` | Substitute points returned by the existing official scorer. Null when no recorded bench order and vice are available. |

The current live ledger's `projections.csv` does not contain `expected_minutes`.
Consequently `minutes_shortfall` remains `null` in live publications, even when
settled minutes are available. A finite diagnostic requires expected minutes frozen
with the decision. Current projections or later captures cannot fill that gap.

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

## Human baseline inputs

Both human rows replay `ownership_template_v2` with the opening budget, club limits,
legal full squad, starting formation, ordered bench and vice captain. They have no
transfer history or chip use. `construction` labels this synthetic replay; these
are not recorded manager decisions or claims about capture-time player eligibility.
Ownership ranks the squad and XI. For the elite row, previous-week elite starter
counts replace ownership and previous-week captain counts rank the armbands.
Settled points never select players or captains.

The decision capture must precede its matching deadline. Outcomes must come from a
checked, finished same-season capture after that deadline and no later than the
publication capture. `source_snapshot_id` names ownership's decision capture or
elite evidence's source IDs; `outcome_snapshot_id` names the checked scoring capture.
The optional `construction` and `outcome_snapshot_id` fields apply to synthetic rows.

`--evidence-root` supplies verified CSV/manifest pairs, from no later than the
system decision capture, matching its season, week and deadline. Elite evidence
must cover the full player pool and the complete Top-100 cohort. Missing ownership,
captures or complete elite evidence leaves the relevant row null. Invalid checksums,
contradictory metadata and infeasible squads refuse publication. Predictions used
for diagnostics come only from the decision's frozen projections, never ownership.

The optional component ledger must match the system's capture and deadline and name
the component-only model. It is settled alongside the system in the same archive
scan. The weekly scoreboard records the evidence and capture archives as inputs;
publication copies the validated preview without rebuilding the baselines.
