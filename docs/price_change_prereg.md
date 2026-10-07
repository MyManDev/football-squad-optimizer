# Price changes at later deadlines: model measurement

Protocol `price_change_study_v1`, fixed by its merge before any run. This is #1013
step 1a, following the owner's 7 October decision to measure first and keep every
price forecast private. It adopts Decision defaults 1, 2, 4 and 5: deadline grain,
the archive followed by one live reading, candidates A and B, and all three pass
clauses. No alternative is selected. Nothing enters a planner under this protocol.

## Scope and reading

The declared archive seasons are `2020-21`, `2021-22`, `2022-23`, `2023-24` and
`2024-25`, pinned to `ARCHIVE_COMMIT` in `data/sources/vaastav.py`. The first is
training only. Each of the other four is held out once; its training set contains
2020-21 and the other three development seasons. All transforms and fitted
parameters for a fold use only its training seasons. A final live fit uses the
five named seasons. Neither a loader's default season list nor 2025-26 is used.
The runner refuses 2025-26 before any loader call or file open for that season.

There is one combined reading, after `2026-11-06T18:30:00Z`, the GW10 deadline,
when the live label inventory has been frozen. It includes the four held-out
archive seasons and the 2026-27 live target deadlines GW4 through GW10. No archive
verdict is taken early under the separate-reading alternative. Before that instant,
the runner may validate schemas and input timing without fitting, predicting,
joining future prices or computing a score. Synthetic tests are allowed.

No candidate association or score has been computed for this protocol. The survey
in #1013 counted observed moves and described fields. The committed
`terminal_value_study` and its note were read as existing negative evidence about
wallet-state prediction, not re-scored. The relevant implementations reviewed were
`experiments/terminal_value.py`, `season_chain.py` and `multi_gw_rehearsal.py`;
their planner, price and acquisition behaviour is unchanged here.

## Identity, horizons and price labels

Join players by stable FPL `code`, within season. Per-season `element` or `id` is
used only to recover that code from the source roster. Exclude manager rows and
retain GK, DEF, MID and FWD. No future roster field is a feature.

An origin is the decision deadline of gameweek g. Horizon h, in 1 through 5,
means the deadline of g+h, not the next night and not a fixture offset. The origin
price P and the target price T are positive integer tenths. The classes, in fixed
order, are `fall`, `no_change`, `rise`, according to the sign of T-P. A move of
two or more tenths is still one fall or rise row. Its full signed magnitude is
retained in the realized-price record and in reported absolute price error.

The flat control always predicts P, with class probabilities (0, 1, 0). It is
reported beside the model. The score reference is the training base rate for the
same horizon: counts of the three classes divided by their total, with no
smoothing. A missing class has zero mass. A horizon with no training rows refuses
the run. Every comparison uses the same complete paired rows.

Each candidate's price is P-1, P or P+1 according to its largest class probability.
Ties choose `no_change` if it is tied, otherwise `fall` before `rise`. The model
therefore forecasts sign and a one-tenth representative move, including when the
realized label is larger. No magnitude learner is selected after seeing results.
Report mean absolute error in full tenths separately for every horizon. A forecast
of a fall is bounded below by one tenth.

## Archive timing and features

Use the archive's collapsed player-gameweek rows, with identical repeated
fixture rows counted once and nonadditive transfer/ownership/price fields never
summed across a double. Refuse conflicting values among a player's repeated rows.
Recover `code` through the existing roster join. Roster names and identifiers may
be read for identity; its end-of-season `now_cost`, ownership, status and totals
must never enter a feature or label.

P at origin g is the price on the player's last row strictly before g, exactly
the previous-observed-row convention of `shift_price_to_deadline`. T uses that
same convention at g+h. Do not treat a row's unshifted value as its own deadline
price. Opening rows with no previous observation are excluded. A target with no
new observation after the origin is excluded and counted, rather than assigned a
flat label from an indefinitely carried price. Future rows supply labels only.

The feature row is the player's last row strictly before g. Its latest fixture
kickoff, including every fixture in that row's gameweek, must precede the origin
clock by at least three hours. At archive grain, the origin clock is that
gameweek's first scheduled kickoff minus 90 minutes, fixed here as a timing proxy.
Rows failing that check, missing fixture times, and origins with no scheduled
fixture are excluded with separate counts. This also excludes late rescheduled
fixtures masquerading as observations available before a later deadline.

These are archive proxies: the archive provides no acquisition timestamp and
does not establish exact historic deadline prices. The price shift and fixture
clock are the declared conservative timing rule, not proof of a historic live
capture. The independent live clause is required and never replaced by archive
scores. Report this timing convention beside every archive figure.

Candidate A has these six feature groups, fixed before data:

1. Net transfers relative to ownership: `(transfers_in - transfers_out) /
   max(selected, 1)` from the feature row. In live data use `transfers_in_event`,
   `transfers_out_event`, and ownership count
   `selected_by_percent * total_players / 100` from that same bootstrap.
2. Last observed gameweek's price change: the feature row's value minus its
   preceding observed row's value. Live uses `cost_change_event`.
3. Change since the season's beginning: the feature row's value minus that
   player's first observed archive value. Live uses `cost_change_start`. The
   archive's first observed price is explicitly a start-price proxy, not the
   end-of-season roster price. Count and report the origin week of that anchor.
4. Current price P, in tenths.
5. Position, one-hot GK/DEF/MID/FWD, no omitted category.
6. Ownership relative to the largest contemporaneously observed ownership:
   selected divided by the maximum selected in the feature gameweek; live
   selected_by_percent divided by the maximum in the same capture. Refuse a
   nonpositive denominator.

Numeric fields must be finite; price and transfer counts must be integral where
the source defines counts. A missing field, missing preceding price observation
or ambiguous identity excludes the player row with its reason. No missing number
is zero, no later row repairs an origin, and no post-origin feature is read.
The first two observed rows establish history; neither is a scored origin without
the required earlier observations. Publish exclusion counts by season and horizon.

## Candidate A: fixed learner

Fit one multinomial logistic regression per horizon, with intercept, L2 penalty,
`C=1`, `solver=lbfgs`, `tol=1e-8`, `max_iter=2000`, seed `20261007` and no class
weights. Standardize the five numeric groups by the training rows' population
mean and standard deviation; a zero training deviation uses scale one. Position
indicators remain unscaled. Do not clip features, tune C, select interactions or
choose a learner on held-out results. Every training row has equal weight.

A fit with fewer than two observed classes, or one that does not converge, is
recorded as unavailable for that fold/horizon. It is not replaced by another
learner or silently assigned the base rate. Any unavailable h=1 fold makes
candidate A's primary verdict insufficient, rather than passing on fewer seasons.
Align the learner's output to the declared three-class order, using zero mass for
a class absent from training. Retain the library/runtime versions in provenance.

## Live capture and deadline-price rule

Read only authorized snapshot roots, including the repository's existing
`data/snapshots` read-only. The runner does not access `C:/sqr` or `C:/sqrweb`, add
a capture, call FPL, or read element-summary. Required later captures must be
retained by the weekly operator in an authorized root.

For origin g use the last pre-deadline `fpl-live` decision capture targeting g.
Require its own season and deadline to match. Two distinct captures at the same
latest instant refuse that origin; never choose by outcome. All features, P and
candidate B fields come from this one origin capture.

For target g+h, use the last capture taken strictly before its deadline and after
the final nightly change before that deadline. Fix the nightly clock to 23:00Z,
the nightly moment stated in #1013; take the latest such instant strictly before
the target deadline. Validate that the target capture's three listed
`game_config.settings.price_change_deadlines` are consecutive future nightly
23:00Z instants. Its `price_change_last_updated` must be at or after the preceding
nightly instant and no later than capture time. If that schedule or update check
fails, the target deadline is missing; a changed nightly schedule needs a new
protocol, not an inferred clock. Do not interpolate a gap or use an after-deadline price.
Use the selected target bootstrap's `now_cost` as T. The target capture may also
serve as the next origin; its price is still read only as the earlier row's label.

The live primary h=1 targets are GW4 through GW10, with origins GW3 through GW9.
Missing origins or labels are listed, including an unavailable GW3 origin. Other
live horizons are reported on target deadlines in that same range. No target
after GW10 enters the reading. A live primary verdict requires at least two
distinct usable target deadlines; otherwise it is insufficient and cannot pass.
No live outcome points, picks or member plans are read for this measurement.

## Candidate B: fixed progress-field rule

Candidate B is live only and predicts h=1. Its rule is an experimental mapping,
not a claim about FPL's undocumented field meanings. In the origin capture take
the three `price_change_projections` entries, offsets 0, 1 and 2. Each must have
a finite `projected_percent` and an integral `likelihood`; the latter is validated
and retained privately as provenance but is not converted into a probability.
The selected progress z is the projected_percent with greatest absolute value;
a tie chooses the lower offset. Define `u=clip(z/100,-1,1)`. Probabilities are
`fall=max(-u,0)`, `rise=max(u,0)`, and `no_change=1-fall-rise`.
The same fixed class-to-price and tie rules apply.

Missing entries, duplicate offsets, a missing or nonboolean calibration flag,
a true `price_change_calibrating`, or a lock extending after the origin capture
make B unavailable for that row. A null lock is unlocked; a non-null lock must
parse as a UTC instant or the row is unavailable. Do not turn
these rows into flat forecasts. Report the omission counts, field availability,
capture-to-next-night and capture-to-target-deadline gaps. The three-night progress
can differ from the later deadline's price; its score against that deadline is
the declared test, without extending or fitting the rule to the intervening nights.

For B compare with the final training base rate on the same live rows, and also
report A and flat-control scores on those exact rows. B needs at least six usable
target deadlines for its interval gate. It never replaces A's archive fit or makes
step 2 eligible by itself. A later wiring PR may replace A's first deadline with B
only if B passes the two live clauses below and the issue's other gates hold.

## Scores, resampling and verdict

Multiclass Brier is the sum, without division by three, of
`(p_class - one_hot_class)^2`. Average over players within each target deadline,
then equally over target deadlines within each season, then equally over the four
held-out seasons. Preserve the paired rows for every difference. Differences are
candidate minus base rate; negative is better. Report the flat control separately.

Use 10000 paired bootstrap draws, NumPy PCG64 seed `20261007`, independently
resampling whole target deadlines with replacement within each season and keeping
all player rows and both arms together. Each draw uses the same equal-deadline,
equal-season mean. The 95% interval is the linear quantiles 0.025 and 0.975.
For B, resample whole live target deadlines by the same rule in its one season.
No row bootstrap, alternative seed, bootstrap repetition or threshold search.

A passes only if all three hold:

1. At h=1 its archive difference has upper interval endpoint strictly below zero,
   and its point difference is strictly negative in at least three of four seasons.
2. At h=1 it names at least one nonflat move per target deadline on average, and
   at least half of its named moves have the correct realized sign. Compute the
   mean named count within seasons then equally across the four; precision is
   the pooled correctly named count divided by the pooled named count. Zero
   named moves fails. A larger realized move of the named sign counts as correct.
3. At h=1 on the paired live primary rows its mean Brier is at or below the final
   training base rate. No positive tolerance is allowed.

B passes its optional first-deadline replacement gate only if its live Brier
difference has upper 95% endpoint strictly below zero, its mean named moves per
usable target deadline is at least one, and at least half have the right sign.
It needs the six target deadlines declared above. Missing required evidence is
`insufficient`, never a pass. Report each clause's inputs and result individually.

All other horizons, full price errors, confusion counts and per-position blocks
are descriptive. They cannot rescue a failed primary clause. A failure or
insufficient verdict closes #1013 as not planned with its failed clause recorded;
no planner setting changes. A pass only permits step 2's separate preregistration.

## Record and private evidence

Step 1b writes `docs/price_change_study.json`, its markdown twin, a note and one
measurements-index row. Name this protocol's merge commit and the run commit,
`ARCHIVE_COMMIT`, explicitly loaded seasons, input file hashes, capture ids,
runtime versions, exclusions and per-class row/move counts. Count decision
deadlines, players and moves for each season, horizon and the live reading.
Check the protocol merge is an ancestor of the run commit before any reading.

Per-player future-price predictions, class probabilities, progress inputs and
any number derived from those predictions stay in an operator-selected private
root outside the repository and outside every served/site/device root. Validate
that separation before writing. They are never committed, rendered, included in
Actions artifacts, copied to device inputs or published. Public records contain
aggregate scores and historical counts, never per-player forecast rows. Public
provenance may contain model id, hashes and input capture identifiers.

No real measurement is run on 9 or 10 October, during a weekly run, or without
claiming and releasing #632's heavy slot. The owner supplies any required capture
retention and run approval. This protocol does not authorize a backend action,
weekly operation, publish, deploy, release, private bucket creation or a real
model call. Step 2's terminal money rate and planner arms require their own
preregistration after this gate; step 3 needs both gates and İbo's review.
