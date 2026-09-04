# Pre-registration: re-measuring S1's clean-sheet clause against an admissible baseline

Written **2026-08-20, before the re-measurement runs**. The baseline, the clause and the
threshold are fixed here so none of them can be chosen after the numbers arrive.

## Why this clause must be re-measured, and what may not change

`team_rating_study` (#139) failed exactly one of its three clauses: the Dixon-Coles
rating's clean-sheet probabilities had to be better calibrated than *a logistic fitted on
the platform's published difficulty rating*, pooled and in all but at most one season.
The Decision 1 ruling has since established that the archived difficulty column is not a
pre-match value — it lives on the same row as the fixture's final score. The clause as
declared is therefore **unmeasurable**: the rating lost to a baseline that had seen the
season it was predicting.

Two things are pinned before any number exists:

- **The clause's structure does not change.** Same Brier comparison, same pooled +
  all-but-one-season threshold, same seasons (2022-23, 2023-24, 2024-25 from gameweek 6),
  same refit discipline, same recalibration treatment for both sides.
- **This cannot retroactively pass S1.** Whatever the outcome, #139's verdict stands as
  recorded. This measurement produces the *measurable form* of the failed clause, dated
  today, under its own contract.

## The admissible baseline

A logistic `clean sheet ~ opponent's previous-season league points + venue`, fitted only
on seasons before the judged one, walk-forward. The previous season's final table is
knowable at every deadline of the following season, which is the whole requirement the
published rating failed. A club with no previous-season table (promoted) carries the mean
previous-season points of promoted clubs in the training seasons — the same measured-prior
idea the rating itself uses.

Reported beside it, not gated: the constant-rate baseline (the training seasons' overall
clean-sheet frequency by venue), as the floor any baseline must clear; and the player
ordering comparison re-run against the new baseline, for the record — the rating won that
clause even against the contaminated baseline, so this can only move in one direction of
interest.

## The gate

The rating's recalibrated clean-sheet Brier must beat the previous-season-table logistic,
pooled and in at least two of the three judged seasons — the original clause's threshold,
unchanged. If it fails, the honest conclusion is that the rating's clean-sheet channel
adds nothing over last season's table, Route C's defensive structure must not consume it
uncapped, and the negative is recorded. The bar is not moved after the fact.
