# Football DEFCON development scope, 28 September 2026

The owner approved option 1 in the current conversation on 28 September 2026:
use 2025-26 as development data only. This is permission from today forward.
It does not establish that a declaration existed before the football studies of
21 and 22 September, or retrospectively preregister their reads. Their results
remain reused-data exploration. The earlier v1 locked-data path stays locked;
this amendment applies only to the separately identified football development path.

2026-27 GW1-5 were already read on 22 September. They can inform development but
cannot be an independent test. The frozen football v1 prospective protocol and
its identity are unchanged. No promotion follows from this permission.

## Declaration before this run

Candidate `football_defcon_shrinkage_dev_v1` estimates the threshold event directly,
instead of inferring its tail from a fitted negative-binomial count distribution.
For each position and observed minute bin (1-59, 60-89, 90+), a Beta(1,1) pooled
event frequency supplies ten prior appearances to each player. These constants
are fixed here, without a search. Predicted minute-bin mass integrates the three
conditional event probabilities; nonappearance and goalkeepers contribute zero.
Historical observed minutes are legitimate training labels, never future inputs.

Only past fixtures settled strictly before the decision cutoff, in earlier
gameweeks, can supply labels. Entire target weeks are excluded, including early
fixtures in double weeks. Missing counts are unknown. Only seasons with the new
DEFCON rule train this head. No current news, injuries or taker ranks are backfilled.

Compare one fixed candidate with the frozen v1 and contextual-DEFCON-only arms on
the complete 2025-26 GW11-38 and already-read 2026-27 GW1-5. Refit the unchanged 22 September comparator heads on the identical recorded
inputs, checking their control point/Brier parity
against the recorded study before evaluating the candidate. Minute, attack,
clean-sheet and residual heads stay fixed. Replace the two-point DEFCON term before
the existing nonnegative point floor. Report equal-week Brier, clipped binary
log loss, calibration bias, point MSE and DEF/MID/FWD diagnostics. The primary population is all outfield players with known labels, including
nonappearances. Goalkeepers are reported as structurally zero, not included to
dilute the event losses. No target appearance filtering is used. This candidate does not produce a
count distribution, so do not claim a count likelihood improvement.

Record code/protocol/input hashes, all 33 paired weeks and failures. Fail closed
on missing folds or control parity errors. No subset selection or parameter
revision after results. These comparisons are exploratory, without a confirmatory
interval or a promotion claim. A future candidate would need its own pre-deadline
capture and separately declared prospective evaluation; this document does not
silently add it to the existing GW6 v1 protocol.

Execution note before candidate evaluation: the first launch could not read the
old research pickle because its optional Arrow reader is absent. No candidate
results were produced. Refit comparators from hash-checked CSV/archive inputs,
keeping the same parity gate, candidate and folds; add no dependency.
