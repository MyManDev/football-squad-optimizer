# Pre-registration: is the squad tail failure the captain's second copy?

Written 2026-08-30, before any number in this study has been computed.

**Labels, stated first because they bound everything below.** This study is
`development_reuse_exploratory`: it re-reads development data that has already been
seen, on the same folds and the same decisions as the measurements it follows. It is
**not a promotion gate** and **not independent confirmation**. Nothing it can say
promotes a model, moves a band, or opens the locked 2025-26 holdout.

## What is being explained

The Phase 2 squad calibration recorded a **failed** verdict
(`shadow_calibration_squad.json`, sha256 `c690efd5…`): S1 passed with mean PIT
0.4921622, and S2 failed with the realized squad score below its own scenario tenth
percentile in **8 of 37** folds — a rate of 0.2162162 against [0.04, 0.16]. Centred,
and too thin below.

The tail diagnostic that followed (`phase2_tail_diagnostic.json`, sha256 `b2855bce…`)
found that a single global dispersion scale is not the answer: `1.45` satisfied both
gates on the validation season but drove 2022-23's tail rate to 0/36, below the floor,
and **no declared level satisfied both gates in all four seasons**, so no global scale
was promoted. The common weekly shock explained little (Pearson 0.382, and a mean
common component of −0.431 on failing folds against −0.360 elsewhere). The captain's
realized error separated the failing folds sharply: **−5.93** against **+0.15**.

The scoring policy counts the captain twice. So one question is left:

> Is the squad-level S2 failure carried by the **extra** captain copy, or does the rest
> of the squad carry the same calibration problem once that copy is taken out?

## The ablation

Two distributions per fold, from the same scenarios and the same already-selected
decision:

1. `full_squad_score` — the frozen instrument exactly as Phase 2 recorded it.
2. `captain_bonus_removed_score` — the same score with **only the extra multiplier copy
   of the captain** removed, on both sides:
   - scenario side: minus the captain's own points in that scenario;
   - realized side: minus the captain's realized points.

**`captain_bonus_removed` does not mean the captain leaves the squad.** The captain
stays in the starting XI and keeps his ordinary starter points on both sides. Nothing
is reoptimized: the same squad, the same starting XI and the same captain are used for
both distributions, and no projection, optimizer, generator or seed changes.

The identity this rests on, per fold and per scenario, and separately on the realized
side:

```
full_score = non_captain_score + extra_captain_bonus
```

where `non_captain_score` is the squad score with the captain still a starter and only
his second copy removed.

**Validity condition, checked and fail-closed.** The evaluator computes
`score = raw_mean + dispersion·(raw − raw_mean) + shift`. At the pre-registered
dispersion of exactly 1.0 this collapses to `score = raw + shift`, which is what makes
the extra copy separable from the evaluated scores without re-implementing any scoring
arithmetic. The study refuses to run at any other dispersion rather than approximating.

## The location convention, and the bias it could hide

The frozen selection-optimism shift of **−7.430702271879578** was fitted for the full
squad score. Removing the captain's second copy removes part of what that shift
corrects, so applying it unchanged to the ablated distribution over-corrects it
downward, which pushes the realized score *up* within its own scenario distribution and
biases the reading toward "the captain did it". That bias points at the interesting
conclusion, so it is declared and bounded rather than footnoted:

- **Primary reading.** The frozen shift is applied unchanged to both distributions. It
  is the frozen instrument minus one term; nothing is refitted.
- **Companion reading.** Both distributions are also read with the location shift set
  to zero, which carries the opposite bias.
- **Disagreement rule.** If the primary and the companion disagree about whether the
  ablated arm's S2 rate is inside [0.04, 0.16], the classification is
  **`inconclusive`**. This study will not claim a localization that depends on which
  location convention was chosen.

## Population

The same canonical fold and decision universe the tail diagnostic used: the
development chain over 2021-22, 2022-23 and 2023-24 after the pre-registered eight-fold
burn-in, plus the frozen 2024-25 evaluation season against the history frozen at the
end of 2023-24. Same scenarios, same seed 11, same 200 draws, same score convention,
same S1 [0.43, 0.57] and S2 [0.04, 0.16] bands. **2025-26 is not read.**

**The classification is computed on 2024-25**, the frozen evaluation season, because
that is the population whose S2 failure is the object of this explanation — not because
of anything this study will find. Every other season is reported as descriptive
sensitivity, and no season-level gate is added.

## Metrics

For each of the two distributions, on each season and on the classification population:

- mean PIT, and its S1 band verdict;
- realized-below-q10 count **and** rate, and its S2 band verdict.

For the captain component:

- the captain's scenario-mean bonus and realized bonus per fold;
- the captain bonus error (realized minus scenario mean);
- its mean and median over the full-score tail-failure folds and over the rest;
- the count of folds with a negative captain bonus error;
- the Pearson correlation between the full-score error (realized minus scenario mean)
  and the captain bonus error;
- a fold-level exact decomposition check, reported as a count of folds where the
  identity holds to floating-point tolerance.

A bootstrap, if reported, is a diagnostic interval only and determines no verdict.

## Classification

No new threshold is invented; the existing S2 band is the only one used.

- **`captain_component_concentrated`** — the full-squad S2 fails above the upper bound
  **and** the captain-bonus-removed S2 is inside [0.04, 0.16].
- **`shared_tail_failure`** — the full-squad S2 fails above the upper bound **and** the
  captain-bonus-removed S2 also fails above it.
- **`inconclusive`** — anything else, including the disagreement rule above, and
  including a full-squad S2 that does not fail above the upper bound on the
  classification population.

## What a result may and may not be said to mean

- `captain_component_concentrated` does **not** mean the captain model is proven. The
  only claim it supports is: *a development ablation localizes the tail failure to the
  extra captain component.*
- `shared_tail_failure` means a captain-specific correction should not be proposed
  before a squad-wide downside-dependence study.
- `inconclusive` means the decomposition did not separate the two, and the next step is
  to report why — not to start another sweep.

No outcome promotes anything, changes any member-facing surface, published field,
contract or evidence status, or publishes a probability, percentage or `P(...)`
anywhere. The 2025-26 holdout stays closed under every outcome.

## Amendment (2026-08-30, before any number was computed)

An adversarial read of the implementation found two places where the wording above was
narrower than the purpose it stated. Both are tightened here, before the study ran.

**A. The veto compares where the ablated tail sits, not merely whether it is inside the
band.** As written, the disagreement rule fired only when the two location conventions
disagreed about `s2_within_band`. Two conventions can disagree maximally and still agree
on that flag: one placing the ablated rate *above* the band and the other *below* the
floor are both "not inside", so the rule would have stayed silent and the study would
have emitted `shared_tail_failure` — a confident word resting entirely on which
convention was chosen, which is what the rule exists to prevent. The comparison is
therefore on the three-state verdict — inside the band, above it, or below the floor —
and any disagreement between the conventions yields `inconclusive`.

**B. The decomposition check verifies the identity it is named for.** The check as first
written compared the study's quantile and mean against the evaluator's own, which is
worth doing, but its third term compared a quantity with itself and so could not fail.
The identity is now checked against the canonical scenario matrix and the fold's own
realized frame: the captain-bonus-removed scenario score must equal the sum of the
starting XI's own columns plus the frozen shift, and the captain-bonus-removed realized
score must equal the sum of the starting XI's realized points. The captain must be a
member of the starting XI, and a fold where either identity fails stops the study rather
than being reported.

**C. The correlation is reported twice, because one of the two is inflated by
construction.** The full-squad score error mechanically contains the captain's error
twice — once through his starter copy and once through the bonus — so its correlation
with the captain bonus error is partly an autocorrelation and cannot be read as evidence
that the captain explains the squad error. The correlation against the
captain-bonus-removed score error, which contains the captain only as a starter, is
reported beside it. Neither decides anything.

No band, seed, fold, decision or arm changes. Every tightening here can only make the
study refuse more often or report more, never claim more.
