# A positional structure for goalkeepers and defenders: protocol

Written on 2026-09-20, **before any of it is fitted**. The population, the candidate, the
fitters, the three clauses of the gate and the drop rule are fixed here so that none of them can
be adjusted once the numbers arrive. Tracking issue: #712. It is Route C of
`docs/opponent_rating_handoff.md`, which named it and left it unbuilt.

## Why this group

Two records, measured independently, put goalkeepers in the same place.

- `participation_calibration`: goalkeepers are the worst-calibrated slice of
  `q_start_given_appearance` by a distance, 738 rows predicted **0.8921** against **0.9864**
  observed, a bias of -0.0943, against defenders at -0.0349 and midfielders at +0.0338.
- `projection_level_audit`: over each decision's top forty per position, goalkeepers read
  **+0.219**, and **+0.472** of that is in what they score when they play rather than in whether
  they play.

A goalkeeper who appears has almost certainly played ninety minutes, and part of his appearance
is priced as a substitute's. The same shape applies to a defender for a different reason: his
points are not a smooth function of a rate. They are an appearance, plus four for a clean sheet,
plus bonus, and a model that multiplies a form rate by an ease factor represents none of that.

`TeamRating.clean_sheet_probability` already emits a probability rather than a scale, so the
object this needs exists.

## What is already measured, and what it does not settle

`opponent_projection_study` measured the **adjustment** shape, a rate scaled by a signal, and
failed: over 110 folds the rating candidate improved error by 0.0016, worsened ordering by
0.00025 and lost 0.909 points a decision. Its per-position coefficients are the reason this
document exists rather than a successor to that one: the slope came out **positive for GK
(+0.2624) and DEF (+0.2276)** and negative for MID (-0.0406) and FWD (-0.0418). The adjustment
failed pooled while pointing one way on this group.

That is a reason to test a different model on this group, not a reason to expect it to pass. A
positive slope in a failed pooled candidate is the weakest kind of encouragement and is recorded
here as such.

## The candidate, fixed

For goalkeepers and defenders only:

```
expected points = P(appearance) x (appearance points + 4 x P(clean sheet) + expected bonus)
```

- **P(appearance)** is the shipped component model's own `appearance_probability`, unchanged and
  not refitted. This candidate replaces the conditional points term and nothing else.
- **Appearance points** are the game's: 1 for appearing, 2 for sixty minutes or more. The split
  is priced by the shipped `expected_minutes_if_appearance`, as `1 + P(60+ | appearance)` where
  that probability is the fraction of the conditional minutes distribution the model already
  carries; no new minutes model is fitted.
- **P(clean sheet)** is `TeamRating.clean_sheet_probability` after the recalibration
  `fit_clean_sheet_calibration` already performs, walked forward over the seasons before the
  judged one and never the judged one itself. **The recalibration is not optional and is fixed
  here**: the handoff records that the raw probability breaks at the top of its range, promising
  better than an even chance on 40 judged fixtures where the clean sheet happened a third of the
  time (0.534 against 0.325). An uncalibrated by-product may not price a defender.
- **Expected bonus** is the per-position mean realized bonus on clean-sheet matches, fitted
  through the same walk-forward split, on played rows only. One number per position, no features.

Nothing else enters. Goals conceded, saves, attacking returns and cards are **deliberately
excluded**, and this is a real limitation rather than a simplification: the candidate prices only
the part of a defender's points that the structure names. The record will say so, and a failure
on that account is a failure of this candidate and not a licence to add terms and re-run.

## The population, fixed

- Rows: goalkeeper and defender rows of the `phase_c_component_oof_v1` out-of-fold table, which
  is the model that decides today.
- Seasons judged: **2022-23, 2023-24, 2024-25**, fitted walk-forward on strictly earlier seasons.
- Target gameweeks 4 and later, so at least three gameweeks stand behind any season-to-date term.
- The locked **2025-26 holdout is not read**, and the record carries that as a computed flag.

## The gate, fixed

Three clauses. All three must pass.

### The lesson this gate is built around

`opening_two_part` passed an ordering clause read over a population that is two thirds players
who never appear, and on the third who do its ordering was worse, roughly halved in two seasons
of three. **A population that is mostly one outcome will let an ordering clause pass on the
outcome nobody needs ordered.** This population has the same shape: most goalkeeper and defender
rows in any gameweek are players who do not appear.

So both reading clauses below are read **on the rows where the player appeared**, because those
are the rows a decision can act on, and the all-rows figures are reported beside them so the
shape of the population stays visible. That choice is made here, before the numbers, and it makes
this gate harder to pass than `opening_two_part`'s, deliberately.

**1. Accuracy.** Mean absolute error against the shipped composition, **on appeared rows**,
pooled improvement with the 90 per cent paired bootstrap lower bound above zero, and an
improvement in **every** judged season. Reported beside it and not gated: the same figures over
all rows.

**2. Ordering.** Within-position Spearman **on appeared rows**, separately for GK and for DEF,
must not fall below the shipped composition's by more than **0.010** in any judged season nor
pooled. The tolerance is the one `opening_two_part_prereg` fixed and is carried unchanged so the
two are comparable; it is not re-derived here and it will not be moved. Reported and not gated:
the same correlation over all rows.

**3. Decision.** The squads a decision would build, both ways, over the same folds, scored on
what happened. Mean realized difference **at least zero** with **at most one** losing season.
Both arms solve under `measurement_optimization_config()` and the record carries each solve's
status, because a proof and an incumbent are different evidence.

## Reported, not gated

- Calibration of the recalibrated clean-sheet probability on the judged seasons, by decile,
  predicted against realized.
- The candidate's error split by whether the clean sheet happened, which is where a structural
  model can be wrong in a way a rate model cannot.
- Goalkeepers and defenders separately throughout, because the two records that motivate this
  point at goalkeepers specifically and a pooled pass could hide a defender-side loss.
- Row counts entering each part, and the count of rows whose club has no rating that gameweek.

## The drop rule

A failure publishes the verdict as produced. The shipped composition stays exactly as it is, the
bar is not moved, and there is no small-fix exception: a changed candidate is a new candidate with
a new declaration. If the gate passes, that makes it eligible for the locked-holdout protocol and
nothing more, and whether to spend `2025-26` is a three-owner decision that this document does not
pre-empt.

A pass here is also **not** a proposal to change `prediction/`. That zone is İbo's, the change
would be proposed on #621 with this record behind it, and nothing is written there on the strength
of a development-fold result alone.

## The record

`docs/positional_defence.json` with its markdown twin and a row in `measurements_index.md`,
written by `scripts/measure_positional_defence.py`, which refuses to overwrite its record because
a gate is read once, refuses the locked holdout before anything is read, and names the seasons it
loaded in its own provenance.
