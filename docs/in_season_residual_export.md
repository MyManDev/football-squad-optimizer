# In-season blend residual export

Contract: `oos_residual_export_v1`  ·  regime: `in_season_carry_over_blend`
Identity: `squadopt-deterministic-baseline` / `in-season-carry-over-v1`

The live risk layer describes a squad's spread by calibrating on a residual
history, and that description is only honest if the residuals belong to the model
making the decision. From gameweek two that model is
`in-season-carry-over-v1`, and the control export already recorded carries
`form_window_05_v1` -- the archive-fed control, a different model. This is the
matching history for the one that decides.

## What is in it

- **101,447 rows** across **147 folds**, seasons 2021-22, 2022-23, 2023-24, 2024-25.
- One row per `(fold_id, player_id)`; every projection paired with the outcome
  read only after that decision point.
- Residual mean -0.3783, standard deviation 2.2171, range -9.4 to 26.3.

## What it must not be used for

**Opening gameweeks.** Every fold here is gameweek two or later, because the model
needs a played gameweek to read. An opening decision is projected from carry-over
and a price prior instead, and mid-season residuals do not describe that regime --
assuming they do would produce a confident-looking interval with nothing behind
it. The manifest states `opening_gameweeks_included: false` so a consumer can
check rather than assume, and the export refuses to build if an opening gameweek
appears.

That refusal is the same answer the opening-week runbook already gives from the
other side: a gameweek-one risk block is `not_requested`, and that is correct
rather than missing.

## What it does not decide

Nothing on its own. It is an input a live decision may calibrate on once the
wiring exists, not a claim that any interval is well calibrated. Whether these
residuals produce honest coverage is a separate measurement.

The locked holdout was not read: the panel is cut to the development seasons
before anything reads a feature window.
