# Pre-registration: a two-part opening projection for players with no record

Written **2026-08-26, before any two-part model is fitted**. The population, both parts, the
fitters, the seasons and every clause of the gate are fixed here so that none of them can be
adjusted once the numbers arrive.

This is not a new idea being declared. `opening_newcomer_note.md` ends by naming its own
successor, including the one wording change it committed to making *before* the next run rather
than after. This document is that commitment, honoured.

## Why

On the real 2026-27 opening capture, **199 of 587 players had no prior record**, and the shipped
prior projects every one of them through a single line: `0.29941 x price in millions`
(`FITTED_OPENING_PRICE_COEFFICIENT`). Measured over 874 such rows across four openings, that line
predicts **1.387** points where **0.686** were scored — a bias of **+0.701**, roughly a factor of
two.

The predecessor found the cause and, in doing so, found why every fix it tried failed:

- **Two thirds of newcomers do not appear at all** (67% / 64% / 72% / 72% by season). The
  coefficient is not wrong; it was fitted on every opening player, most of whom have a record and
  play, and then applied to a population that mostly does not.
- **Ownership and the game's own xP fix the level and break the order.** `M2` and `M3` improved
  pooled MAE by +0.363 and +0.401 with intervals well clear of zero, and made within-position
  Spearman *worse in every season* — control 0.515/0.471/0.511 against `M2`'s
  0.483/0.364/0.433. The note's reading: ownership mostly tells you **whether** he plays, price
  orders **the ones who do**, and a single additive line makes those two compete.

So the shape to test is the one that stops them competing:

```
expected points = P(plays | ownership, price, position) x E[points | plays, price, position]
```

Whether the *product* preserves ordering is genuinely open, and is what this run measures — a
cheap, widely-owned player can still overtake an expensive, unowned one. The mechanism is
plausible; that is the reason to run it, not a reason to expect it to pass.

## Population, fixed

Identical to `opening_newcomer_study_v1`, so the two studies are comparable row for row:

- Seasons read: `2020-21` through `2024-25`. The earliest is excluded from evaluation because
  nothing precedes it, which is also what makes the newcomer/mover distinction possible at all.
- Seasons judged: **`2022-23`, `2023-24`, `2024-25`**.
- Rows: opening-gameweek rows with `has_prior_record == False`.
- Minimum training rows before a season is judged: **60**.
- **The `2025-26` locked holdout is not read.** `OpeningStudyConfig.__post_init__` refuses it
  rather than trusting the runner to leave it alone.

## The two parts, fixed

Both are fitted **walk-forward**: for each judged season, only rows from strictly earlier seasons
are fitted on.

**Part one — P(plays).** Target is `minutes > 0` at the opening gameweek. Design is
`[intercept, ownership_share, price_m, DEF, MID, FWD]` — the four positions as indicators with
`GK` as the reference level. `ownership_share` is the predecessor's own definition, the player's
`selected` count as a share of that week's most-selected player, and a row with no published
value reads **0.0**, which is the behaviour already in `build_opening_rows` and is inherited
rather than re-decided here.

**Part two — E[points | plays].** The predecessor's per-position least squares through the
origin on `price_m`, fitted **on played rows only**. That restriction is the whole structural
difference from `M1`: `M1` fits one price slope over all newcomers, so the two thirds who never
appear are absorbed into the slope and flatten it. Here they are priced by the first factor
instead.

**The product** is clipped at zero, as the shipped prior is.

Nothing else enters either part. The game's own `xP`, the opening fixture, published team
strength and carried club strength are all available in the row builder and are **deliberately
excluded**: `M3`–`M4b` measured them and they worsened ordering, and adding a feature after
seeing a result is the failure this document exists to prevent.

## The fitters, fixed

- P(plays): **`_fit_logistic`** (`experiments/team_rating.py:654`) — Newton's method, a `1e-6`
  ridge for conditioning, a 50-iteration cap and a `1e-9` step tolerance. Already reused across
  modules by `team_rating_cs.py`. **No new fitter and no library solver**, so there is no
  iteration count, tolerance or solver choice introduced that could move between environments.
- E[points | plays]: **`_fit_through_origin`** (`opening_newcomers.py:353`), unchanged.
- The only randomness anywhere is the declared bootstrap: **2,000 resamples, seed 0**, paired, as
  in the predecessor.

## The gate, fixed

Three clauses. All three must pass.

**1. Accuracy — unchanged from the predecessor**, so a pass here means what it meant there.
Pooled mean-absolute-error improvement over the control, with the **90% paired bootstrap lower
bound above zero**, *and* an improvement in **every** judged season.

**2. Ordering — restated, and this restatement is the entire reason the pre-registration comes
before the run.** The predecessor failed `M1` for producing ordering *identical* to the control:
within a position it is a positive multiple of price, so its within-position Spearman matched to
three decimals, and the wording asked for a strict improvement. Identical is not an improvement,
so `M1` failed a clause it had not actually violated. The note recorded that the wording would be
restated **before** the next run rather than relaxed after one. It is:

> Within-position Spearman must not fall below the control's by more than **0.010** in any judged
> season, nor pooled.

The tolerance is a number here rather than an argument later, and it is chosen on the
predecessor's committed measurements rather than on anything from this run: `M1`'s ordering
differed from the control's by **less than 0.001**, while the candidates that genuinely worsened
it did so by **at least 0.032** (`M2`: −0.032 / −0.107 / −0.078). Any threshold inside that gap
separates the two cases; 0.010 is the round number inside it. It will not be moved.

**3. Decision — unchanged from the predecessor.** The opening squad is built both ways through
`compare_decisions` and scored on what actually happened. Mean realized-squad-points difference
against the control **≥ 0**, with **at most one** losing season.

## Reported, not gated

- **Calibration of P(plays)**: predicted against realized play rate by decile, per judged season.
  A first factor that orders well but is systematically over-confident would leave the product's
  level wrong for a reason the accuracy clause alone would not name.
- Bias, MAE and ordering restricted to newcomers who actually played — a diagnostic in the
  predecessor and a diagnostic here.
- The count of rows entering each part, and the count with no published ownership value.

## What a failure publishes

The verdict as produced. A clean negative is the deliverable, in the shape `terminal_value_study`
and `overlap_calibration` already established: the recorded conclusion would be that separating
the play probability from the scoring rate does not fix the opening prior's level without costing
its order, the shipped prior stays exactly as it is, and the bar is not moved. There is no
small-fix exception — a changed candidate is a new candidate with a new declaration.

## What this is not

- **Not a promotion.** Clearing a development gate makes a candidate eligible for the
  locked-holdout protocol and nothing more, and spending the `2025-26` holdout is a three-owner
  decision.
- **Not an admissibility ruling on ownership.** `selected_by_percent` sits in
  `AMBIGUOUS_TIMING_COLUMNS`, and `data_followups.md` records that it "stays excluded on the
  original conservative grounds and is a separate question". This study reads the archive's
  per-gameweek `selected` at gameweek one, where no lag is possible, which is admissible for a
  *study* and is **not** a route to a feature. That question is untouched here.
- **Not this season's business.** The 2026-27 opening gameweek was decided, settled and published
  in August 2026. Nothing measured here can alter it either way.
- **Not a change to `expected_points_rate`.** This is the opening prior, a different component
  from the one #43 and #88 contend for, so it neither occupies nor unblocks that slot.
