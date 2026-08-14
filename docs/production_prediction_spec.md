# Production prediction specification

Status: **implemented**, first candidate. The evaluation gates in this document are
pre-registered and frozen: they were written before the production model existed and must
not be edited once a comparison has been run.

Every number below is measured on the pinned archive, and each one names the rows it was
measured on. Where a claim has not been measured yet it says so rather than being asserted.

This document is the contract between the production prediction pipeline and the rest of the
system. The optimizer, the uncertainty layer and the scenario generator do not read it —
they read `PredictionSnapshot`. This document exists so that a reader can tell what went
into that snapshot and why each input was allowed.

## Model shape

Expected points are produced in two stages rather than one:

```
expected_points = expected_minutes / 90 * expected_points_per_90
```

The reason is that the two quantities fail differently. A first-choice striker who is
injured and a fringe striker who is fit can carry the same recent points-per-90 while having
nothing in common as a selection. Collapsing availability and scoring rate into one
regression forces a single model to explain both, and the residual it produces cannot be
attributed to either. Splitting them also matches how the uncertainty layer already thinks:
residual scale is learned per player, and a player whose variance comes from rotation is a
different object from one whose variance comes from finishing.

Both stages are fitted on the same leakage-safe feature table and on the same chronological
slice. Neither stage may read the target gameweek's outcome.

### The rate is deliberately plain, for now

The first candidate's rate is the current-season scoring rate with a shrunk carry-over
fallback — close to what the baseline already uses. That is a measurement strategy, not
modesty. Any difference from the baseline then comes from two identifiable sources, the
appearance decomposition and the calendar, and can be attributed before anything more
elaborate is layered on. Adding model capacity first would leave the improvement
unattributable, which is the position the two-stage split exists to avoid.

### The calendar

The panel sums a player's minutes and points across every fixture inside a gameweek, so the
number of fixtures a club plays is part of the projection rather than a refinement to it.
Measured across the six supported seasons:

| Fixtures | Rows | Mean points | Mean minutes |
| ---: | ---: | ---: | ---: |
| 1 | 149,117 | 1.175 | 27.6 |
| 2 | 6,919 | 2.339 | 53.6 |
| 3 | 39 | 2.923 | 75.9 |

A double gameweek is worth 1.990 times a single one. The deterministic baseline predicts
0.917 times as much for one, because it cannot see the fixture list at all, and 1,937 rows in
the panel exceed ninety minutes with a maximum of 204.

Expected minutes therefore scale with the fixture count and cap at that many full matches,
and a club with no fixture projects to zero whatever its players' history says — history
cannot override an empty calendar.

### Appearance decomposition

Expected minutes is the product of how often a player features and how long when he does,
each over the same window, rather than a single minutes average. The two are different
questions and one number conflates them: a fringe player who completes ninety minutes
whenever selected and a starter regularly substituted on the hour can log identical minutes
averages while being different selections. Only one of them is a rotation risk.

The rate is minutes per gameweek *featured*, not per fixture, because the panel stores a
gameweek total and cannot say whether a player featured in one of two fixtures or both. That
leaves a slightly inflated base rate for histories containing double gameweeks — 6,919 of
156,075 rows — and removing it needs player data at fixture grain the archive does not
publish.

## Availability is a rule, not a feature

The archive records `status`, `chance_of_playing_next_round` and `news` after the fact. Their
as-of time cannot be recovered, so a coefficient fitted on them would be fitted on
information we would not have held at the deadline. They are therefore excluded from the
model matrix, and the exclusion is mechanical: they never enter the feature builder.

Live capture changes what is knowable, not what is trained. Once we stamp `captured_at_utc`
ourselves and can prove capture preceded the deadline, availability becomes usable at
inference as an explicit multiplier applied *after* the projection:

- A stated chance of playing sets the multiplier to that fraction. It takes precedence over
  the status, because the source publishes it exactly when it has something quantitative to
  say.
- Where no chance is stated the status decides: available is 1, injured, suspended,
  unavailable and not-in-squad are 0, and doubtful without a stated chance is a half, which
  is the only neutral reading of unquantified uncertainty.
- A player with no availability record at all is treated as available, because silence is the
  normal state for most of a roster and reading it as doubt would penalise every unremarkable
  player.
- An unrecognised status stops the run. The field is undocumented, and a wrong guess about
  the meaning of the most common status would misprice the whole roster at once. A capture is
  normally inspected with a dry run before a deadline, which is where such a change surfaces.

The vocabulary is measured, not assumed. The 2026-27 pre-season capture publishes, across 584
squad-eligible players: `a` 514, `i` 35, `u` 18, `d` 14, `s` 3. A chance of playing is stated
for exactly 83 of them — the same 83 that carry a news timestamp — quantised to 0, 75 and
100. Applied to a flat projection the rule zeroes 56 players, reduces 14 to three quarters
and leaves 514 untouched.

Players reduced to zero are **reported, not removed**. Pool membership belongs to the
decision layer, and dropping rows inside the projection could make a squad problem infeasible
for reasons that layer never sees. Every multiplier the rule applies is reported alongside the
projection, because a quietly halved projection is indistinguishable from a model that
predicted half as much and those are different claims.

This asymmetry is deliberate. The rule uses live availability; the model does not learn from
historical availability. Revisiting it requires a source whose historical snapshot timing is
verifiable, which the archive is not.

## Feature inventory and timing classification

Every feature carries a timing class. Pre-match features may be read from row `t`. Outcome
features may only be read from rows strictly before `t`, which is why every aggregation over
them passes through `shifted_rolling_mean` or `shifted_rolling_sum`. Grouping is
`("season", "player_id")` and does not change.

| Feature | Source | Grain | Known at deadline | Missing-value policy | Timing risk |
| --- | --- | --- | --- | --- | --- |
| `price_tenths` | canonical panel, row `t` | player-gameweek | Yes | Non-nullable by contract | None. Price is shifted one gameweek back at ingest, and the first appearance keeps its own price |
| `position` | canonical panel, row `t` | player-gameweek | Yes | Non-nullable by contract | None |
| `team_id` | canonical panel, row `t` | player-gameweek | Yes | Non-nullable by contract | None |
| `minutes_last_w` | shifted rolling mean of `minutes` | player-gameweek | Derived from `< t` only | `NaN` until history exists; never back-filled | Would leak if unshifted. Enforced by the single shift primitive |
| `points_last_w` | shifted rolling mean of `total_points` | player-gameweek | Derived from `< t` only | `NaN` until history exists | As above |
| `points_per_90_last_w` | shifted rolling ratio | player-gameweek | Derived from `< t` only | `NaN` when shifted minutes are zero | As above |
| `prior_seasons_minutes_per_gameweek` | completed earlier seasons | player-season | Yes | `NaN` for a player with no earlier season | Reads only completed seasons, never the current one |
| `prior_seasons_points_per_90` | completed earlier seasons | player-season | Yes | `NaN` for a player with no earlier season | As above |
| `fixture_count` | fixture table, target gameweek | team-gameweek | Yes | Zero for a blank gameweek, stated rather than imputed | Reads the target gameweek's own fixtures only, which are published before the deadline |
| `home_fixture_count` / `away_fixture_count` | fixture table, target gameweek | team-gameweek | Yes | Zero for a blank gameweek | As above |
| `opponent_attack_strength` | our own estimate from shifted results | team-gameweek | Yes | Position-pooled prior for a promoted team with no record | Computed from outcomes strictly before `t`, so it is an outcome aggregation and is shifted |
| `opponent_defence_strength` | our own estimate from shifted results | team-gameweek | Yes | As above | As above |

Deliberately excluded, with the reason rather than an omission:

- `xP` — the archive scrapes it after the match. It is an outcome dressed as a projection.
- `selected_by_percent` — snapshot timing unverified in the archive.
- `status`, `chance_of_playing_next_round`, `news` — see the availability section above.
- `fixture_difficulty` from the source — opaque, source-specific, and its within-season
  stability is unverified. Ingested for provenance, never consumed as a feature. Our own
  strength estimate is used instead because it is reproducible from shifted history.
- `starts`, `expected_goals`, `expected_assists` — present only from 2022-23 onward.
  Adopting them would shorten the training window to four seasons and, more importantly,
  would change the fold set so paired comparison against the existing baseline and Ridge
  benchmarks would no longer be like-for-like. Deferred to its own issue.

## Cold-start precedence

A player with no in-season history is not a single case, and the two stages do not run out
of signal at the same moment. Each stage therefore has its own ladder, and the point where
the two-stage product stops applying is stated rather than left implicit.

### The minutes stage

1. **Current-season appearance history.** How often a player features, multiplied by how
   long when he does.
2. **An observed absence.** History exists and says he featured in none of the recent
   gameweeks, which projects to zero. This is a measurement, not a gap; folding it into the
   fallback would discard a real observation.
3. **Cross-season carry-over**, shrunk toward zero. He has a record, just not this season,
   and last season may no longer describe him — a transfer, a new manager, a different depth
   chart. Shrinking states that uncertainty instead of projecting last season forward
   unchanged.
4. **Nothing.** The estimate is left missing.

### The points stage

1. **Current-season scoring rate** from shifted history.
2. **Cross-season carry-over rate** for a player with a record but not this season.
3. **The fitted opening price prior**, for a player with no record anywhere.

### Where the product stops applying

The two-stage form is `expected_minutes / 90 * expected_points_per_90`, and it is used
wherever both stages have signal.

It does **not** apply at the bottom rung, and that is a correctness point rather than a
convenience. The price prior estimates *expected points* directly — `coefficient *
price_tenths / 10` — not a per-90 rate. Multiplying it by `expected_minutes / 90` would
scale a quantity that already accounts for playing time by playing time a second time,
which double-counts the prior and pushes every genuinely new player toward zero. So for a
player whose minutes stage produced nothing, the price prior supplies `expected_points`
directly and the product is bypassed.

This is why the minutes stage leaves its last rung missing instead of taking a constant.
A fabricated minutes figure would satisfy the formula and silently corrupt the one case the
formula cannot describe. Leaving it missing keeps the two claims separable: "we do not know
how long he will play" and "we estimate his points from price alone" are different
statements, and only the second is one we can defend.

### Guarantees

The final `expected_points` is never missing and never negative. A player who reaches the
end of both ladders without a projection is an error, not a zero.

Which rung fired is recorded per player in the snapshot diagnostics, for both stages.
"We measured this" and "we fell back" are different claims, and a squad built mostly from
fallbacks should be visibly that rather than indistinguishable from a measured one.

The price prior is refitted per fold on an expanding window rather than applied as one
global constant. A constant fitted across all seasons and then used inside earlier folds
would have seen those folds' own opening outcomes. The effect is confined to opening
gameweeks, because walk-forward folds skip them by default, but the fold story should be
uniform regardless.

## Pre-registered evaluation gates

The operational control is the deterministic baseline at `form_window = 5`,
`bench_weight = 0.1`, `risk_aversion = 0`. The Ridge reference is a mandatory second
comparison and does not become the control.

Baseline superiority gate, on the same development folds:

- Mean improvement of at least `+0.5` squad points per gameweek.
- 90% moving-block bootstrap lower bound at or above `0`.

Ridge comparison gate, on the same folds:

- Mean difference at or above `0`.
- 90% lower bound at or above `-0.5`.

Additional conditions, all of which must hold:

- Every fold feasible.
- Every leakage test passing.
- At least one of MAE or RMSE improved against Ridge.
- The other of the two degraded by no more than 5% in relative terms.
- No serious systematic per-position bias.

The observed `+4.8108` Ridge-over-baseline difference from the 2024-25 smoke benchmark is
not a threshold. It is one season's realised result and is recorded here only so that nobody
later mistakes it for a target.

Note what the two gates imply together: because the Ridge gate requires the production model
to match Ridge, the binding constraint in practice will be whatever Ridge actually achieves
across the full development fold set, and the `+0.5` baseline gate will not bind unless
Ridge underperforms there. This is intended, and it is why Ridge is measured across all
development folds before the production model is built rather than after.

Ridge's figure is now measured and recorded in
[learned_benchmark_development.md](learned_benchmark_development.md): `+3.1156` over 147
development folds, with a 90% moving-block interval of `[+1.5306, +4.9524]`. That is the bar.

## Measured so far

Prediction error against the deterministic baseline, on the 101,447 development rows outside
opening gameweeks:

| Slice | Rows | Baseline MAE | Production MAE | Baseline RMSE | Production RMSE |
| --- | ---: | ---: | ---: | ---: | ---: |
| Overall | 101,447 | 1.1237 | 1.1224 | 2.2335 | 2.2051 |
| Single fixture | 96,335 | 1.0956 | 1.0862 | 2.1526 | 2.1261 |
| Double gameweek | 5,112 | 1.6541 | 1.8041 | 3.4173 | 3.3636 |
| Players who featured | 41,930 | 2.2246 | 2.1855 | 3.2870 | 3.2228 |

Bias, as mean predicted minus realized:

| Fixtures | Baseline | Production |
| ---: | ---: | ---: |
| 1 | +0.0588 | +0.0428 |
| 2 | -0.9987 | +0.1724 |

The bias row is the substantive result. The baseline under-projects a double-gameweek player
by a full point because it cannot see the calendar, and that systematic error is essentially
gone. Double-gameweek MAE rises while its RMSE falls, which is the expected shape: predictions
for those players move up, so the many who still do not play cost more absolute error while
the large misses shrink.

Against Ridge on the same rows — MAE 1.1300, RMSE 2.0991 — production is ahead on MAE and
behind on RMSE by 5.05%, which sits on the edge of the 5% tolerance above. Stated as it
stands rather than as it is hoped to end up.

### The decision metric, and the gate verdict

Realized squad points across the 147 development folds, same folds and same optimizer for
every candidate. Both runs agree with the recorded Ridge benchmark on the baseline fold for
fold, so this is one comparison rather than three.

| Candidate | Mean realized | Paired difference over baseline | 90% interval |
| --- | ---: | ---: | --- |
| Baseline | 53.7755 | — | — |
| Ridge | 56.8912 | +3.1156 | `[+1.5442, +5.0000]` |
| Production | 57.4150 | +3.6395 | `[+1.7959, +5.7551]` |

Against the two pre-registered gates:

| Condition | Required | Measured | Verdict |
| --- | --- | ---: | --- |
| Mean over baseline | `>= +0.5` | +3.6395 | pass |
| 90% lower bound over baseline | `>= 0` | +1.7755 | pass |
| Mean over Ridge | `>= 0` | +0.5238 | pass |
| 90% lower bound over Ridge | `>= -0.5` | **-1.6466** | **fail** |

**Verdict: no promotion. The deterministic baseline remains the operational control.**

The candidate is robustly better than the baseline and only nominally better than Ridge. Its
paired difference against Ridge has a standard deviation of 16.3311 across a win/tie/loss
record of 70/5/72 — fold by fold it is a coin flip — and the per-season means tell the same
story: `+1.5946`, `+1.4722`, `-0.3514`, `-0.5946`. It wins the first two development seasons
and loses the last two.

One prediction made before this was measured turned out to be wrong and is recorded rather
than quietly dropped. The paired difference against Ridge was expected to have *lower*
variance than either candidate's difference against the baseline, on the reasoning that two
models are correlated with each other. It is higher: 16.3311 against 14.8056 and 12.8145. The
two models disagree with each other more than either disagrees with the baseline, because
they are betting on different things — production sees the calendar, Ridge has a learned
functional form, and neither has both.

### What may and may not follow

The gate result is now known, which constrains what honest iteration looks like. Tuning this
candidate until it clears a threshold it has already been measured against is fitting to the
gate, and the governing issue forbids it in as many words.

A further candidate is legitimate on one condition: the change is declared before it is
measured, and it is measured once. The direction the numbers point at is a learned rate stage
that also sees the calendar, since that is the one combination neither current candidate has —
but writing that here is a hypothesis, not a licence to iterate until something passes.

## Determinism and provenance

- Input frames are never mutated in place.
- The same input and the same config produce byte-identical output.
- Row ordering is deterministic and does not affect any feature or prediction.
- Training-only imputation and standardisation. Statistics are computed on the training
  slice and applied to the target rows, never the reverse.
- Provenance carries model name, model version, feature contract version, training cutoff
  and training-data fingerprint, and the resulting projection carries a prediction
  fingerprint.

## Known limitations

- Historical postponement is unrecoverable. The archive places a rescheduled fixture in the
  gameweek where it was eventually played, so no "this fixture was postponed" signal can be
  trained. Live capture can observe it; the model cannot learn from it.
- Historical availability is unusable, as set out above. The rule applies from the first live
  capture onward and cannot be validated against past seasons.
- Opponent strength is not yet a feature. The fixture table carries opponent identity and
  home or away for every gameweek, and the aggregation exposes difficulty summaries, but the
  first candidate uses only fixture counts. Source-published difficulty stays out of the model
  because it is opaque and its within-season stability is unverified; a strength estimate
  computed from shifted results is the intended replacement and has not been built.
- The rate stage is deliberately plain, so the model currently has no way to distinguish two
  players with the same recent rate facing very different opponents.
- Minutes per gameweek featured is not minutes per fixture, which leaves a small inflation for
  histories containing double gameweeks, as set out above.
