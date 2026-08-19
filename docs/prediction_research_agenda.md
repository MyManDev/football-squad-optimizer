# Prediction Research Agenda

Owner: data / data mining. The question this side owns:

> How do we produce the best available, leakage-safe, calibrated future information for the
> optimizer?

This document records the **method** and the **open queue**. It deliberately does not contain a
schedule. Per [ADR 0003](architecture/decisions/0003-measurement-artifacts.md), a committed
document is a record; a twelve-month plan written here would be wrong at the first reordering
and would then be quoted as though it were a commitment.

The far items below are direction, not a backlog. They say what this side would investigate and
in roughly what dependency order, so that a decision made now can avoid closing a door later.

## The method

Every candidate goes through the same shape, and the discipline is the point rather than the
ceremony:

```
control model
    ↓  out-of-sample residuals
candidate signal
    ↓  does the residual still move with something the model could have seen?
declaration, frozen and fingerprinted
    ↓  exactly one measurement
verdict recorded as produced, pass or fail
```

Four rules make it worth doing:

1. **Look for signal in the residuals, not in the raw outcomes.** A feature that correlates
   with points may already be spent by the existing feature set. `opponent_strength_signal.md`
   is the worked example: the effect is larger in the residuals than in the outcomes (1.24x for
   attackers, 1.06x for defenders), which is what makes it worth pursuing rather than merely
   real.
2. **Declare before measuring.** The declaration is frozen and fingerprinted before the run,
   because iterating against a threshold you have already seen is fitting to the threshold. See
   [candidate declaration review](candidate_declaration_review.md).
3. **Measure once.** A changed candidate is a new candidate with a new fingerprint and a new
   review. There is no small-fix exception.
4. **Score the decision, not only the prediction.** Prediction quality and decision quality are
   different quantities and can disagree. A candidate with better RMSE that picks a worse squad
   has not helped. The frozen objective is `single_gameweek_realized_squad_points_v1`;
   `paired_decision_metrics` (`backtest/learned.py:364`) is what reports it.

Rule 4 is the one most likely to be skipped under time pressure, and the one that most changes
conclusions.

## The open queue

Strictly sequential, because both open candidates change the same component —
`expected_points_rate` — and measuring them together would make the result unattributable.

### 1. Issue #43 — a learned rate combined with the calendar

Blocked on people, not code. Both fingerprints reproduce, the candidate is implemented, the
leakage guards now match the frozen builder's, and
`python -m scripts.run_candidate_gate --confirm-frozen` is the one command that produces the
verdict. What is missing is the architecture/CI side's Stage A review; the freeze needs all
three owners (`issue43_handoff_acceptance.md:45`).

When it runs, the record must name the executing machine — `fit_learned_rate` solves a ridge
system through LAPACK, which is not bit-identical across machines.

### 2. Issue #88 — give the scoring rate the opponent it faces

Does not start until #43's verdict is recorded. The signal evidence is already measured
(`opponent_strength_signal.md`): attackers spread +0.162 across opponent-defence quartiles and
are monotone across all four; goalkeepers and defenders spread +0.322 against opponent attacks
but are not monotone.

`features/strength.py` already estimates both sides through the same shifted primitive every
other rolling feature uses, and `attach_opponent_strength` produces
`opponent_attack_strength` and `opponent_defence_strength`. Worth knowing before starting: **no
production path consumes it today.** The only non-test caller is the measurement study, so the
work is wiring an existing estimate into the rate, not building a new estimator — which is also
why the two sides must enter separately, as the issue requires.

## Direction

Not scheduled. Ordered by what each one needs from the ones before it.

**Time-of-knowledge as a first-class property.** Today the guarantee is a `shift(1)` inside one
primitive (`features/rolling.py:101`) plus a per-column timing classification in
`data/schema.py` (`PRE_MATCH_COLUMNS`, `OUTCOME_COLUMNS`, `AMBIGUOUS_TIMING_COLUMNS`), and it is
enforced by mutation tests rather than by types. That is stronger than most projects manage and
it is still a convention. The live path already has the real concept — a capture instant
compared against a published deadline — and the archive cannot prove the same thing. Making the
distinction explicit, rather than implicit in which code path you are on, is the foundation the
rest of this list stands on.

**Data-quality contracts.** Duplicate player-gameweeks, impossible minutes, price jumps, team
mapping drift, identifier drift across seasons, schema drift at the source. The rules and their
semantics belong to this side; running them in production belongs to the platform side.

**Expected minutes as its own model.** The two-stage split already separates minutes from rate.
Taking it further — appearance probability, minutes given appearance, and points rate as three
estimates rather than two — would make rotation and injury risk legible to the optimizer instead
of buried in a single expected-points number.

**Probabilistic prediction.** Quantiles rather than a symmetric conformal radius, so the
scenario and CVaR machinery consumes a distribution the prediction side produced rather than one
inferred downstream. **This one has a hard prerequisite:** the hand-off contract cannot carry a
distribution today — `prediction/integration.py:94` drops every column outside the six required
ones — so it starts with a change to `REQUIRED_COLUMNS`, which is a shared boundary. See the
calibration seam in [ownership](architecture/ownership.md).

**Multi-horizon forecasting.** The horizon builder currently projects one information state and
scales it by fixture count (`linear_fixture_count_scaling_v1`), and says plainly that it will
grow overconfident by an amount nobody has measured. `horizon_decay` measures the drift.
Modelling each horizon separately, and calibrating each separately, is what would let the
planner's horizon length be chosen on evidence.

**Dynamic team strength, hierarchical priors, regime change.** Opponent strength from a rolling
mean is a starting point; latent team state, partial pooling for cold-start players, and
detection of role or manager changes are all ways of spending information the current features
leave on the table.

**Learned models, then decision-focused learning.** A ladder from the Ridge reference through
gradient boosting before anything neural, every rung on the same folds and judged on decision
outcome as well as prediction error. The end of that road is training against decision regret
rather than squared error — at which point the objective is the optimizer's, and this side's
work and the optimization side's stop being separable.

## What this side does not decide

Promotion. Clearing a development gate makes a candidate eligible for the locked-holdout
protocol and nothing more, and spending the 2025-26 holdout is a three-owner decision
(`fw10_holdout_plan.md:36`). The deterministic baseline remains the operational control until
something beats it under a declaration that was frozen first.
