# Private learned score-state football experiment

Issue [#1067](https://github.com/MyManDev/football-squad-optimizer/issues/1067),
step 1, prepares the sixth requested family. It provides private source contracts,
a fitted physical goal process and a separately invoked fixed-fifteen experiment.
The evidence in this step is invented fixtures and independent mathematical
oracles. No real source is admitted, no live route invokes it and no improvement
in realized FPL points is measured.

## Research basis and scope

[Dixon and Robinson's birth-process study](https://rss.onlinelibrary.wiley.com/doi/pdf/10.1111/1467-9884.00152)
motivates modelling scoring as a process whose intensities can change during a
match. [Maia and colleagues](https://arxiv.org/html/2312.04338v1) estimate
log-linear intensities with predictable match context. Their Brazilian league
results do not supply PL coefficients for this implementation. This model learns
its own six coefficients from accepted chronological training observations.

Score state is observable only during an actual match. A predeadline forecast
therefore integrates future score paths starting at 0:0 instead of feeding the
eventual score into player features. Leading, tied and trailing alone are not a
three-state Markov chain: the transition back to a tie depends on the exact goal
difference. This implementation retains every supported integer difference.

The initial family changes physical goal expectations and clean-sheet survival.
It preserves the existing player appearance/minute law and attacking recipient
shares. It does not learn substitutions, red cards, tactical role transitions or
a legal joint club XI. An observed association between score and substitution
does not identify an intervention policy; those extensions need their own input
and evaluation protocols.

## Immutable causal source contract

`football_score_snapshot_v1` records the original native model version, physical
home/away goal means, forecast playing duration, original basis SHA256 and its
fit cutoff, temporal evidence, complete paired fixture calendar and full captured
club roster. `football_score_fixture_input_v1` is its typed representation.
Every player retains either four native minute bins or seven native roles, with
the explicitly declared matching representation and model version.

Each supported player state supplies credited FPL minutes, physical entry and
exit instants, and an explicit `not_playing`, `normal_substitution` or `full_time`
policy. Source evidence must establish these intervals. They are not derived
from FPL minutes, position or a presumed start. A dismissed player is unsupported
and refuses this source contract.

The physical clock is
`physical_playing_minutes_including_stoppage_excluding_breaks_v1`. First and
second period durations include their actual additional playing time and omit
the interval between periods. Outcome observations retain their own actual
duration and ordered periods. Forecast duration stays a predecision input.
Credited FPL minutes remain a separate quantity for the 60-minute scoring gate.

`football_score_outcomes_v1` contains ordered physical goals, beneficiary club,
scorer club, own-goal identity, final physical score, separately settled FPL
goal/assist credits and complete observed player exposure. Physical own goals
change the beneficiary's score without inventing an attacking scorer. Final
physical goals, FPL credits and each player's participation reconcile separately.
A known scorer must be on the pitch at the recorded physical goal instant.
An assister's earlier touch does not require presence at the later goal instant.

Exact bytes are checked against SHA256 before strict JSON parsing. Receipt
assertions bind provider/version, rights evidence, publication and capture clocks;
they do not authenticate upstream licence or data truth. Duplicate keys,
unknown schema, coerced identities, inconsistent clocks and incomplete coverage
refuse. Missing exposure is never filled with zero.

All training headers are preflighted before any outcome body is opened. The
protected 2025-26 season, the target and later gameweeks, later seasons, unsettled
outcomes and sources not available before their cutoff refuse. The original
native forecast's own fit cutoff must precede its historical decision. A named
allowlist records the permitted development seasons. Current data cannot fill
a historical observation.

## Learned predictable intensity

Let `H(t)` and `A(t)` be physical goal counts and `D(t)=H(t)-A(t)`. With original
native physical means `gH,gA` and predecision duration `T`, baseline intensities
are `bH=gH/T` and `bA=gA/T`. Three fixed thirds of that forecast clock index `k`.
Tied intensity remains native; one shared lead and trail coefficient is fitted
per third:

```text
lambdaH(t) = bH * exp(beta[k,lead]  * I[D(t-) > 0]
                   + beta[k,trail] * I[D(t-) < 0])
lambdaA(t) = bA * exp(beta[k,lead]  * I[D(t-) < 0]
                   + beta[k,trail] * I[D(t-) > 0])

negative_log_likelihood(beta)
  = sum_observed_intervals integral(lambdaH + lambdaA) dt
    - sum_physical_goals log(lambda_scoring_side(t-))
    + l2 * ||beta||^2 / 2
```

The design evaluates the score immediately before each goal, then updates the
difference. Physical own goals use their beneficiary side. Historical exposure
ends at the observed actual duration while its offset and third boundaries keep
the original forecast clock. No goal-time or final-duration outcome is inserted
into a target forecast. Zero native intensity cannot explain a historical goal
and refuses instead of receiving an invented floor.

The analytic gradient is checked against finite differences. Bounded L-BFGS-B
fits all six coefficients together, with numerical parameter support and explicit
regularization configuration recorded in metadata. Neither a manually assigned
lead/trail sign nor a score multiplier is a policy rule. The complete fit is
immutable and replaced atomically. A failed refit retains the previous fit.
Receipts bind source/outcome hashes, settlement clocks and the full typed training
record separately, alongside coefficients, objective, gradient and configuration.

## Path integration and clean sheets

The exact integer difference is a sufficient state for these intensities. From
every full score `(h,a)` with the same difference, a home goal maps to `d+1`
and an away goal to `d-1` with identical rates. Lumping the full score lattice
therefore preserves physical goal rewards and the interval survival queried here.
It does not justify adding absolute-score-dependent features to this version.

Sparse nonnegative uniformization advances the piecewise generator from 0:0.
Augmented reward rows integrate home and away physical goal counts. For a player
entering at `on`, its initial difference distribution comes from the unrestricted
history `0 -> on`. Only opponent-goal transitions are killed on `on -> off`.
Its own club's goals still change state within that interval. After a normal exit,
later concessions cannot change that interval's survival.

For player-state weights `w[i,s]`, credited minutes `m[i,s]` and captured physical
intervals, the clean-sheet scoring probability is

```text
CS[i] = sum_s w[i,s] * I[m[i,s] >= 60]
                  * P(no opponent physical goal in [on[i,s],off[i,s]])
```

The interval law is different from substituting the learned final mean into
`exp(-mean_opponent_goals * credited_minutes/90)`. Score-path dependence and the
physical entry interval matter. The
[official FPL rules](https://www.premierleague.com/en/news/4661029) distinguish
the credited 60-minute threshold, which excludes stoppage time, from concessions
while on the pitch. A normal substitution ends exposure. Dismissal semantics
require a later supported model rather than that normal-exit rule.

## Numerical bounds and refusal

The grid retains `[-K,K]`. A dominating Poisson process has each third's maximum
total intensity over leading, tied and trailing and whole-fixture mean `M`.
Leaving the grid requires at least `K+1` physical goals. Analytic bounds are

```text
lost_path_mass <= P(Poisson(M) >= K+1)
lost_goal_first_moment <= M * P(Poisson(M) >= K)
```

Chernoff bounds choose a sufficient radius. Lost paths remain an explicit deficit;
the code does not renormalize retained probabilities. The positive uniformization
series has separate omitted probability and first-moment bounds. Truncation
bounds are supplemented by a declared floating allowance of `256 * machine_eps`.
This allowance is practical numerical accounting, not a certified interval
arithmetic proof of every sparse operation. Independent full-score dense/ODE
and Poisson oracles test the returned probabilities, goal rewards and intervals.

The default tolerance is `1e-11`, maximum difference radius 256 and per-piece
series work is bounded. An insufficient grid, underflow, unsupported numerical
work, excessive deficit or exceeded mass/moment budget refuses. Predictions and
private experiment receipts retain the bounds, explicit deficit, selected grid,
model/input hashes and actual interval/propagation counts.

## Native binding, points and fixed-fifteen path

Before learned composition, a zero-coefficient process must reproduce both
original physical means and every supported native clean-sheet moment within
the numerical budget. Matching a physical mean alone is insufficient. Intervals
are not moved to force this check to pass. A native basis unavailable from its
original chronological producer refuses real use.

For each full club, original physical-to-credited goal and assist fractions and
the original normalized player recipient shares convert the new physical mean
to player attacking counts. Each club's credited total closes before the owner's
players are selected. Individual physical bounds remain enforced. Original
appearance, p60, expected minutes, role probabilities, defensive contribution,
residual, shares and resource fields are preserved exactly.

Raw points change by the goal, assist and clean-sheet component deltas under the
same recorded season's rules. They are then clipped once per fixture. The old
Poisson clean-sheet validator is used on the native basis, never to silently
overwrite the new process result. New private component/experiment versions
identify the changed law and bind its complete receipt.

Weekly points use one supplied player-week eligibility factor:
`mu_week = eligibility * sum_f max(0, raw_points_f)`. Weekly positive-minute q is
the exact sealed served native value. It is not reconstructed with an independent
DGW union, rescaled again or multiplied by a second learned appearance model.
Calendar-complete blanks and zero physical channels retain structural zero.

Control and disabled paths preserve the served values and resources without
opening the new source or model. The zero-process ablation is distinct from that
exact control. A separately invoked role adapter searches at most 128 evaluations
of the same owned fifteen with official formation, ordered reserves, captain,
vice-captain and autosubs. It does not change transfers, prices, bank, chips or
transfer policy and makes no global optimum claim. An independent appearance
world oracle checks the official fixed-squad result.

## Synthetic implementation validation

The final focused run passes 374 cases with one existing optional research-bo
skip: 144 source, 57 model, 61 integration and 112 relevant existing cases.
Ruff/format, strict mypy on all three new source modules and all six import
contracts pass. No full local suite is run.

Source tests independently bind an unknown own-goal scorer's opposing club and
each goal's period clock; those guards cannot hide behind final credit or score
checks. Model tests use finite differences, independent Poisson and full-score
dense/ODE oracles. Integration starts from raw invented source bytes, fits the
model, composes native components/weekly points and compares two legal actions
using independently enumerated appearance worlds. The learned preference flips
the first XI, reserve order and vice-captain under the same captured inventory
and resources. This is a synthetic action witness, not realized FPL benefit.

Control/disabled, nullable four-bin representations, zero physical channels,
negative raw point clipping, full seven-role supports, complete-calendar blanks,
receipt/resource tampering and captured native-moment failures are covered.
Served appearance values must lie within the marginal union bounds; an SGW
reduces to its original eligible fixture q and a BGW to zero. A coherent interior
dependent DGW value is preserved without substituting an independent product.

Fifteen controlled faults on private copied modules are caught with passing
originals: four source guards, five model chronology/numerical/receipt rules and
six application scoring/eligibility/60-minute/q/inventory/native-proof rules.
Original implementation hashes remain unchanged. These checks are supported by
the committed test assertions; private logs are supplementary local observations.

Three invented 240-fixture model fits take 0.137 to 0.139 seconds and each
66-player prediction about 0.011 seconds, with 57 difference states and 12 cached
intervals. These are private local observations, unverified by committed runtime
artifacts, and establish no production request budget.

## Remaining real-input gates

The committed source/model/integration tests establish implementation behavior.
They contain invented players, intervals, scores and source evidence. They do not
establish an actual independently produced native basis or source admission.
No inspected source supplies the complete permitted PL 2020-21 through 2024-25
physical goal timeline, authentic historical native offsets, player intervals
and final FPL credits together. Historical publication clocks, temporal FPL
identity, coverage and model-use rights require explicit admission.

[Wyscout's public research release](https://www.nature.com/articles/s41597-019-0247-7)
includes earlier PL event material rather than this requested archive. The
[StatsBomb open-data repository](https://github.com/hudl/open-data) is a separate
source with its own licence and competition coverage; its public files do not
establish these project's complete inputs or permission gates. Neither source
is downloaded, joined or fitted in this step.

FM traits can be later predictors or ANN inputs only after #1057 rights,
authentic season vintage and reviewed player mapping hold. No FM trait creates
a physical on/off interval, historical score event or missing FPL credit here.
The six families remain separately versioned and unwired. Actual cumulative
integration waits for accepted predecessor merges, required Ibo/designated
reviews and a separate invocation PR. The unanswered population, chronological
fold, metric and threshold decisions in #1004, #1009 and #1016 remain unanswered.
No outcome from protected 2025-26 is opened. No weekly run, backend, deployment,
member page or promotion is changed by this step.
