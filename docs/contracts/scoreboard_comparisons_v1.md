# Weekly scoreboard comparison extension

The additive `gameweeks[].comparisons` field extends `provisional_league_ui_v1`.
Older publications without it remain readable. Each week carries six rows in fixed order:
`system`, `base`, `elite_xi`, `ownership_template`, `league_mean`, `game_mean`.
League and game means are separate because their populations and scoring bases differ.

Each row carries `net`, `scoring_basis`, `source_snapshot_id`, and `diagnostics`:

| Diagnostic | Definition |
| --- | --- |
| `zero_minute_starters` | Count of frozen starting XI with settled minutes equal to zero |
| `minutes_shortfall` | Sum of projected minus settled minutes, only for starters who played |
| `captain_shortfall` | Expected captain points minus the realized ordinary captain bonus; excludes the extra triple-captain copy |
| `autosub_recovery` | The existing official scorer's autosub points; excludes vice-captain recovery |

Unfinished or unchecked weeks carry null comparison values. Unknown projections and
unrecorded bench order/vice-captain remain null, never inferred from outcomes. Legacy
decisions retain `named_eleven_no_autosubs`; a decision explicitly carrying
`ordered_bench_player_ids` and `vice_captain_player_id` can use
`official_autosub_captain_v2`. The implementation reuses the existing scoring functions.
Bench Boost counts the whole squad; Triple Captain adds the recovered captain bonus.
New ledger entries freeze those two missing fields with the existing
`optimizer_projection_order_v1` completion policy at decision time. Existing entries
are not migrated. This freezes ordinary projection ordering; it does not enable the
pending start-model-based bench selection.

Settlement is a read-only publication computation from the newest finished-and-checked
event-live capture available by the publication capture time, within the same season.
Player identities use persistent codes. Frozen ledger files are verified by the existing
loader and remain unchanged. Existing ledger outcomes remain readable when a corresponding
event-live capture is unavailable; their error columns remain unknown.

The bare component row requires a separate frozen ledger passed with
`--baseline-ledger-root`. It must use the same season and decision capture. No post-hoc
division by an elite multiplier is treated as a counterfactual decision.

Human baselines are reconstructed decisions labelled `constrained_ownership_template_v2_replay`.
Both reuse the existing legal squad/lineup builder and opening budget. They have no
transfer history or hits and must not be described as real managers' net results.
Ownership comes from the frozen decision's pre-deadline bootstrap. The elite baseline
uses complete Top-100 lagged starting counts and chooses its armbands by lagged captain
counts, from verified `player_evidence_v1` files captured no later than that decision.
Missing, incomplete or later evidence yields a null row. It is a legal synthetic squad,
not an unconstrained top-eleven list. Counts never become expected-point predictions.

The league mean uses members' captured points minus their transfer charges. The game mean
is `average_entry_score` from the bootstrap and is labelled as the source average.
The analysis and league pages show only points, counts and minutes; research rates are
not part of this extension.
