# Three-state participation pre-registration

This document declares the two things
[`phase_c_component_model_prereg.md`](phase_c_component_model_prereg.md) deliberately left
open when it wrote *"when a verified start label is available"*: **which label, over which
population**, and **which estimator family** may produce the three state probabilities it
already defines. It does not restate that contract, redefine the states, choose a promotion
threshold, read the locked holdout, or change the operational control.

It exists because opening the archive's start label is a pre-registration act, in the words
of `features/component_targets.py`: *"Declaring a source and a population is a
pre-registration act, not something a builder may do on its own."*

## What is already contracted, and is not reopened

`phase_c_component_model_prereg.md` fixes the state algebra:

```text
p_none       = 1 - p_appearance
p_substitute = p_appearance * (1 - q_start_given_appearance)
p_start      = p_appearance * q_start_given_appearance
```

and prescribes the admissible composition in the same breath:

```text
p_appearance             = P(A = 1 | X)
q_start_given_appearance = P(S = 1 | A = 1, X)
p_start                  = p_appearance * q_start_given_appearance
```

Nothing here weakens that, and the object this work fits is **`q_start_given_appearance`**,
estimated on the appeared subpopulation. `p_appearance` keeps its existing estimator.

That is a deliberate choice against re-estimating both halves at once. A single multinomial
over the three states would also produce a `p_appearance`, as the derived sum
`p_substitute + p_start` — and that number is not free to move. It reaches
`control_expected_points`, which is the promoted operational control, so replacing it would
be a promotion carried out by a refactor. The three states are still what is modelled and
still what is reported; they are reached by the factorisation the contract already fixes
rather than by a joint fit that would change a number this work may not touch.

The structural requirement is met without a repair step: `q` lies in `[0, 1]` by
construction, so `p_start <= p_appearance` holds by algebra rather than by clipping. The
identity check in `evaluation/component_metrics.py` holds by definition rather than by
tolerance. The three state probabilities follow as the contract defines them:
`p_none = 1 - p_appearance`, `p_substitute = p_appearance * (1 - q)`, `p_start = p_appearance * q`.

## The label

`starts` from the pinned archive (`vaastav_fpl_manifest.json`, commit `8c97b2ad…`), read as
`starts > 0` at player-gameweek grain, consistent with the existing contract's *"`start`
means starting at least one fixture"* for a double gameweek.

Two facts about this column were measured before it was declared, and both narrow the
population. Neither is visible from the column's presence:

**2022-23 carries the column but not the values, and is excluded entirely.** In
`2022-23/gws/merged_gw.csv`, `starts` sums to exactly zero for GW1–GW15 while minutes over
those gameweeks are normal — about 19,700 each, the same as later ones. From GW16 it is
correct and reads 220 per single gameweek, which is ten matches times twenty-two starters.
Zero starts beside nineteen thousand minutes is an absent column, not a season in which
nobody started.

The whole season goes, not only its first third, and the reason is the canonical contract
rather than convenience. `data/cleaning.py` refuses a missing value in a canonical column —
*"canonical data must be complete, so supply the values or drop the column"* — so there is no
way to carry `starts` for part of a season: it is either complete for that season or absent
from it. Keeping the zeros would put a false value in canonical data, which is the worse of
the two. So the adapter declares the column per season, and 2022-23 is not one of them.

**2023-24, 2024-25 and 2025-26 are complete**, verified gameweek by gameweek: no gameweek in
any of the three sums to zero. **2025-26 is the locked holdout**
(`PHASE_C_LOCKED_HOLDOUT_SEASONS`) and is excluded from this work — not loaded, not listed,
not hashed and not filtered; a run that reads it is void rather than caveated. It is named
here only because the archive adapter must say truthfully which seasons carry the column.

## The population, as measured

| Season | Rows |
| --- | --- |
| 2023-24 | 29,725 |
| 2024-25 | 27,605 |
| **Total** | **57,330** |

State distribution over that population:

| State | Rows | Share |
| --- | --- | --- |
| no minutes | 34,380 | 0.5997 |
| substitute appearance | 6,230 | 0.1087 |
| start | 16,720 | 0.2916 |

The label is internally consistent: **no row carries a start with zero minutes**, and the
6,230 substitute rows are exactly those with minutes and no start.

Two seasons, not four. A count taken from the column's presence alone reads about ninety
thousand rows; what survives the holdout and the completeness rule is 57,330. The difference
is recorded here so that no later reader reconciles a larger number against this population
and concludes that rows went missing.

## The estimator

A penalised binary logistic regression for `q_start_given_appearance = P(S = 1 | A = 1, X)`,
fitted on the rows where the player appeared, and composed with the existing appearance
estimator as the contract above prescribes.

**Not ordered**, and the reason is structural rather than a fit statistic: a rested
first-choice player and a fringe squad player land in the same state for opposite reasons,
so a single latent index cannot move them together. Goalkeepers break an ordered model a
second way, their substitute state being close to unreachable rather than merely rare.
Neither the factorisation used here nor a joint multinomial imposes that ordering; what
separates them is which numbers they re-estimate, and the factorisation re-estimates none
that are already promoted.

The conditioning is what makes the population smaller than the panel: only appeared rows
carry a start label to learn from, which is 22,517 of the 55,661 declared rows — 6,084
substitute appearances and 16,433 starts.

**Team strength is a required control, not an optional term.** Strong teams have deep benches,
substitute earlier and win anyway, so a rotation model without that term will attribute the
squad's quality to the player's role. The control is built inside the prediction layer from
the existing `shifted_team_rolling_mean` primitive in `features/rolling.py`; nothing here
imports the laboratory tree.

Hyperparameters are declared, not searched. The fitted object is refit in process and
identified by a version string and a fingerprint, following `component_models.py`; no
estimator is serialised to disk.

## What will be read

Calibration before discrimination: **Brier score, log loss and a ten-bin reliability
diagram**, pooled and by position, for two quantities:

- **`q_start_given_appearance`**, the object this work fits, scored on appeared rows against
  the start label — the direct reading of whether the new estimator is calibrated;
- **`p_start = p_appearance * q`**, the composition, scored against the same label — the
  reading that matters to anything downstream, and the one that can be wrong even when `q`
  is right, because it inherits `p_appearance`'s calibration.

`p_appearance` alone is **not** re-measured here. It is the promoted control's own number and
`docs/phase_c_component_evaluation.json` already reports it; re-reading it under a different
population would invite a comparison that is not like-for-like.

The split is out-of-sample within the declared population: fitted on 2023-24 and scored on
2024-25. Both seasons are development data, neither is the locked holdout, and the reading is
descriptive — it promotes nothing and moves no threshold.

A tree ensemble is not fitted in this work; whether one improves *calibration* rather than
merely discrimination is a later question and needs its own declaration.

## What this does not do

- **No promotion.** No version is pinned in `IN_SEASON_CONTROL_MODEL_VERSIONS`; pinning one
  there is the promotion decision and is not taken here. The operational control is unchanged.
- **No paired comparison against existing component records.** The population above is two
  seasons and the component records are 147 folds over four, so the fold sets differ and a
  paired reading would not be like-for-like. `production_prediction_spec.md` deferred exactly
  this to its own issue, on the ground that adopting `starts` "would shorten the training
  window"; this is that issue, and the answer is that the window is shorter still than it
  assumed, and no such comparison is claimed.
- **No decision change.** The bench ordering continues to rank by expected points. Carrying a
  start probability to the boundary where an ordering could read it is a separate, declared
  step and changes no order.
- **No member-facing probability.** Nothing here is published to a member.

## Amendment to a standing declaration

`rotation_evidence_prereg.md` states that `START_TARGET_STATUS` remains `unavailable` and
`START_TARGET_SUPPORTED_SEASONS` remains empty *"for the archive; nothing here changes
either, because nothing here touches the archive"*, and explains the emptiness by the adapter
mapping only columns present in every supported season.

This document touches the archive, and supersedes that sentence in one direction only: the
archive start label is declared over the population above. The prospective 2026-27 settled
capture path that `rotation_evidence_prereg.md` declares is unaffected — it keeps its own
source, its own eligibility mask and its own population, and this work reads neither.
