# Pre-registration: Phase 2 shadow calibration — the deciding model's own spread, measured internally

Written **2026-08-28, before any Phase 2 shadow measurement exists or runs**. The gates
below are fixed here so they cannot drift toward the numbers once they arrive. Nothing
in this document changes what members see: **no outcome of any measurement under this
protocol publishes a probability, percentage, quantile, interval or spread to member
advice or to the site** — the honesty envelope (`PUBLISHABLE_FIELDS`,
`FORBIDDEN_FIELD_PATTERN`) stays closed regardless of every result.

## Which side of the closed line this is

Three pre-registered constructions of windowed crowd-relative probabilities failed as
declared (`rival_calibration`, `anchored_calibration`, `overlap_calibration`) and the
line's own stop-rule binds: those probabilities are not honestly claimable from this
scenario model, and re-attempting them requires a changed scenario model and a new
pre-registration naming it. **This protocol does not reopen that line.** It calibrates
the *own-side* quantities the stop-rule never touched:

1. **Player expected-points intervals** for the model that actually decides live from
   gameweek 2 — `in-season-carry-over-v1` — whose residual export exists
   (`docs/in_season_residual_export.md`) but is explicitly "an input, not a
   calibration claim". Every fitted calibration committed so far wraps the archive-fed
   control (`form_window_05_v1`); none wraps the deciding model.
2. **Squad-level distribution honesty** (PIT / tail rates) for the same model, via the
   existing scenario-audit instrument.

Rank / league-position probability is out of scope (no ground truth exists — the
archive has no mini-league). Multi-week (h>1) aggregation is out of scope and may not
ride out through this protocol; it requires its own pre-registration.

## Population and split

- **Eligible development seasons**: 2021-22, 2022-23, 2023-24, 2024-25.
- **Fit/evaluation split** (the committed control-record pattern): fit on
  2021-22..2023-24, evaluate frozen on 2024-25 — no refit after any evaluation number
  is visible.
- **Walk-forward discipline**: residual history visible to a fit is strictly earlier
  than every evaluated fold (`validate_residual_history` ordering); opening gameweeks
  (gameweek ≤ 1) are refused, never inferred from GW2+ residuals.
- **Live-season shadow loop** (2026-27): each settled gameweek may be shadow-scored
  only with a calibration fit on strictly earlier folds. The live loop **abstains** —
  it makes no claim — before **8 settled gameweeks** exist (the
  `min_history_folds` precedent).

## Forbidden holdout

The locked 2025-26 season is **never read** — a no-read protocol, not a no-influence
protocol. Any loader invoked under this protocol receives an explicit season list;
artifact provenance records the actually loaded seasons; `holdout_untouched` is
derived from the loaded data, never written as a literal; and a run whose loaded data
contains 2025-26 aborts without writing artifacts (the boundary pattern fixed in the
strategy bench's post-run amendment).

## Residual provenance, bound

A shadow calibration is conditional on the model it wraps
(`issue38_calibration_decision.md`): it must name **one** `oos_residual_export_v1`
export — label, model identity, `table_sha256` — and that manifest must be **committed
to the repository before the measurement runs**. Calibrating one model's spread on
another model's residuals is refused (the #45 rule; `live/risk.py`'s
`MODEL_MISMATCH` is the enforcement precedent). Declared prerequisite, recorded here
so satisfying it is not tuning: the in-season export currently has **no committed
manifest** — it must be regenerated, pass `run_artifact_preflight`, and have its
fingerprint block committed before the first binding run.

## Metrics and gates, fixed before any number

Horizon: **h=1 only**, per fold, on the frozen evaluation season.

- **Gate P1 (player coverage)**: empirical coverage of the 0.90 interval satisfies
  |coverage − 0.90| ≤ 0.03 pooled, and ≤ 0.05 within each fixture group
  (`single`, `double_plus`) that carries ≥ 200 player-gameweek rows; a thinner group
  is reported, not gated. Mean width is reported as a finding, never gated.
- **Gate S1 (squad PIT location)**: mean PIT over evaluation folds lies in
  [0.43, 0.57].
- **Gate S2 (squad lower tail)**: the realized-below-q10 rate over evaluation folds
  lies in [0.04, 0.16].
- Blank fixtures are represented zeros by construction and sit outside every
  calibration cell; they are never imputed.

**Resampling unit**: development population — fold-level bootstrap, 5000 resamples,
90% intervals; live-season weekly series — season-aware moving block bootstrap, block
length 4 (`PromotionPolicy` defaults, as in the strategy bench). **Seeds, in-doc**:
bootstrap seed **0**; scenario draws seed **11** (the rival-line precedent); both are
recorded in the artifact and may not move.

**Minimum sample**: no gated claim from fewer than **30 evaluation folds**
(development) or **8 settled gameweeks** (live loop). Below the floor the outcome is
**ABSTAINED**, which is distinct from FAILED.

## Outcomes and their consequences

- **Pass (all gates)** unlocks exactly one thing: `shadow_status:
  calibrated_internal` in the internal shadow report. No member-facing surface, no
  published field, no contract, and no strategy evidence status changes on a pass.
- **Fail (any gate)** is a valid, recorded result: the negative is committed, the
  thresholds do not move, and there is no retry, re-tune or reinterpretation without
  a new pre-registration.
- **Abstain** (insufficient sample, missing or mismatched manifest, opening gameweek,
  unprovable inputs) is reported with its reasons — never silently skipped, never
  converted to a pass or a fail.
- **Missing data is never zero**: a fold with a missing outcome fails closed
  (`evaluation_spec` rule); a row the capture cannot prove abstains from its cell.

## Public-output prohibition

Shadow artifacts are internal measurement records: they live in `docs/` (committed)
or `data/` (local, gitignored), **never under `web/public`**; the shadow report
contract (`shadow_calibration_report_v1`) is not referenced by `ui_view_v1` or any
site payload; and guard tests sweep the published league tree for probability-shaped
keys and text in both languages. Every committed measurement artifact under this
protocol carries its `docs/measurements_index.md` row.

## Corrective-run amendment — serialization and create-once boundary

The first player-level execution exposed two protocol defects before review: its
residual manifest did not declare the measured nine-decimal serialization rule, and
its report writer used a check-then-write sequence that was neither crash-safe nor
safe under concurrent writers. That artifact is therefore **non-binding**. Its numbers
do not satisfy this protocol and cannot unlock any status.

The thresholds, split, gates, seeds, and sample floors above remain unchanged. Before
the corrective run, the exporter must serialize floating-point values to exactly nine
decimal places and declare `predicted_points_decimals: 9`; the consumer must reject a
missing or different declaration. The report writer must complete and fsync a sibling
temporary file, publish with an atomic no-overwrite link, compare a losing writer with
the winning bytes, and remove its temporary file. Concurrent identical and conflicting
writers are tested. The binding report must also record start and completion UTC,
elapsed seconds, deterministic seed, and an explicit warnings list. Only a clean-tree
execution after these rules are committed is eligible to replace the non-binding
artifact.

## Squad-gate amendment (2026-08-29): the S1/S2 protocol, frozen

**Written 2026-08-29, before any squad-level measurement of the target model exists or
runs.** The original protocol above names gates S1 and S2 but leaves their
operationalisation to "the existing scenario-audit instrument", and a read of that
instrument found four choices it does not fix — which squad is scored and from whose
projections, the selection-optimism location shift, the scenario count, and the
residual population that feeds the generator. Each moves the result, so each is fixed
here rather than at implementation time. The thresholds, split, sample floors and
seeds above are unchanged; this amendment adds no gate and relaxes none.

### What is frozen

1. **Target model.** `in-season-carry-over-v1` — model name
   `squadopt-deterministic-baseline`, feature contract
   `in-season-carry-over-features-v1`. The archive-fed control
   (`deterministic_baseline` / `form_window_NN_v1`) is **not** the subject and may not
   supply the scored decision, the scenarios, or the shift.
2. **Scored decision.** Per fold, the risk-neutral deterministic squad, starting XI and
   captain chosen by `optimize_squad` from the target model's own projections.
3. **Realized scoring.** The existing canonical `score_realized_squad_points` under
   `realized_squad_points_v1`. No new scoring formula is written for this protocol.
4. **Development seasons.** 2021-22, 2022-23, 2023-24.
5. **Frozen evaluation season.** 2024-25.
6. **Frozen selection-optimism shift.** One scalar, fitted only on chronological
   out-of-sample development folds:

       shift = -mean over development folds of (raw scenario mean score - realized squad score)

   where the raw scenario mean is the pre-shift, pre-scale mean. **No 2024-25 fold may
   enter this fit.** The expanding-window "online" variant is not this protocol's
   shift: it produces a different number per fold and, on an evaluation population,
   fits on the evaluation season's own outcomes.
7. **Scenario count.** Exactly 200.
8. **Scenario seed.** Exactly 11.
9. **Residual population.** In development, each fold sees only residual folds strictly
   earlier than itself. During the frozen 2024-25 evaluation the residual population is
   **frozen at the end of 2023-24** — 2024-25's own earlier weeks do not join the fit,
   so all 37 evaluation folds are scored against one identical history.
10. **Dispersion.** None; scale exactly 1.0.
11. **Double-gameweek scale.** Exactly 1.0. Not tuned in this protocol.
12. **Lower quantile.** Exactly 0.10, read with the instrument's existing linear
    interpolation rule, unchanged.
13. **Bootstrap.** Fold-level, 5000 resamples, 90% interval, seed 0.
14. **Gates, inclusive at both bounds.** S1: mean PIT in [0.43, 0.57]. S2:
    realized-below-q10 rate in [0.04, 0.16].
15. **Outcome.** A failing P1, S1 or S2 makes the full result **failed**. A missing
    gate, missing provenance or a sample below the declared floor makes it
    **abstained**. There is no re-run with changed parameters.

### Scientific disclosure

This amendment was written before any target-model S1/S2 binding measurement existed.
The previously recorded mean PIT of 0.07 belongs to a different instrument context —
the archive-fed control's squad, under its own projections and its own shift — and was
not used to select or tune any parameter above. The bands in clause 14 are the bands
the original protocol declared; this amendment did not touch them.

### Still unfixed, and therefore blocking a binding run

Reading the instrument found three further controls that change which squad is chosen
or which folds are fitted, and that neither the original protocol nor the decisions
above name. They are recorded here rather than chosen, because choosing a control
after seeing what it does to a gate is the failure this programme exists to prevent.
**No binding S1/S2 run is eligible until a further amendment fixes them.**

- **`bench_weight`.** `optimize_squad` cannot be called without one, and the two
  precedents disagree: the in-season benchmark that measured this model uses the
  library default 0.1, while the scenario audit that computes S1/S2 uses 0.0. It
  changes the selected squad, therefore the PIT and the tail rate.
- **Decision universe.** Whether the squad is chosen over the fold's whole roster or
  over a reduced candidate pool. The only existing squad instrument decides over a
  pool; the whole roster is a different problem with a different answer.
- **`min_history_folds`.** The generator's default of 8 drops the earliest eligible
  folds from any population it governs, which silently reshapes the development fit
  that produces the frozen shift. Whatever value is used must be declared, and the
  resulting fold count, first fold and last fold recorded.

Until that amendment exists, an implementation must refuse to supply these values by
default: they are required inputs with no fallback, and a run that cannot name them
does not start.

**Closed by the second amendment below**, dated the same day and written before any
S1/S2 number existed. The three controls are fixed there; this section is kept as the
record of what was open and why, not as a live blocker.

## Second squad-gate amendment (2026-08-29): the remaining controls, fixed

**Written 2026-08-29, still before any target-model S1/S2 measurement exists.** The
runner that would produce one has never been executed against the archive; no mean
PIT and no tail rate for this model's squad has been read by anyone. The first
amendment named three controls it refused to choose, and an implementation review then
found three more that the generator was inheriting from its library defaults rather
than declaring. This amendment fixes all six, plus the reporting rules they imply. It
adds no gate, relaxes none, and moves no threshold.

### What is frozen

16. **`bench_weight` = 0.1.** The live optimizer's own default
    (`OptimizationConfig.bench_weight`), which is the weight the product actually
    decides under and the weight the in-season benchmark that produced this model's
    residual export used. The scenario audit's 0.0 is deliberately not chosen:
    calibrating a weight the product does not use would measure a squad no member is
    ever shown.
17. **Decision universe = the full roster.** The product's real selection space is
    every eligible player in the fold, so that is what the scored decision is chosen
    over. A reduced candidate pool is a different problem with a different answer.
18. **`min_history_folds` = 8.** The canonical existing default of `ScenarioConfig`.
    Because it drops the earliest eligible folds, the artifact must record the shift
    fit's resulting fold count, first fold id and last fold id.
19. **`min_player_observations` = 8.** The canonical default, now declared.
20. **`player_scale_shrinkage` = 10.0.** The canonical default, now declared.
21. **`player_location_shrinkage` = None.** The canonical default: every component
    stays centred, and no per-player location term enters the scenarios.
22. **Bootstrap, and what it may not decide.** Fold-level, 5000 resamples, 90%
    interval, seed 0, over the evaluation folds' own per-fold values. It is
    **diagnostic only**. The gate decision is taken on the pre-registered point
    estimate — mean PIT for S1, the below-q10 rate for S2 — against the clause 14
    bands. An interval that straddles a bound neither rescues a failing point
    estimate nor overturns a passing one.
23. **S2's bounds are unchanged, and the tail is reported as a count as well as a
    rate.** The band stays [0.04, 0.16] exactly as clause 14 declared it. Because the
    evaluation population is 37 folds, the attainable rates near that band are
    1/37 ≈ 0.027, 2/37 ≈ 0.054, 5/37 ≈ 0.135 and 6/37 ≈ 0.162: S2 is therefore decided
    by whether the number of below-q10 folds is between 2 and 5 inclusive. The
    artifact records the count beside the rate so that a reader sees the granularity
    the gate actually has. This is a disclosure about the instrument, not a change to
    the gate.
24. **No inherited default may stay unnamed.** Every parameter of the generator,
    evaluation and optimizer configuration the run actually constructs is recorded in
    the artifact's provenance, read from the constructed objects themselves rather
    than from a hand-kept list, so a library default that changes underneath the
    protocol shows up as a changed artifact instead of a silent difference.
25. **Report contract.** The full-protocol verdict is written under
    `shadow_calibration_report_v2`, which requires a report to declare the
    pre-registered gate families it answers and refuses `calibrated_internal` unless
    every declared family carries a measured, passing entry. The `v1` contract keeps
    exactly the meaning it had when its artifacts were recorded and stays readable;
    the two committed v1 reports are unaffected and still replay byte for byte.
26. **P1 is merged from the recorded player-level artifact, and only if it is bound to
    the same export.** The full-protocol report carries P1's gate results as measured
    by the player-level runner, and the merge is refused unless that artifact's model
    name, model version, feature contract version, residual table SHA-256, export
    label, seasons and cutoff fold id are identical to the ones this run is bound to.
    Two instruments' evidence may not be added together unless they measured the same
    thing.

### Scientific disclosure (II)

The six values in clauses 16 to 21 are the live product default or the library canon,
and were chosen for that reason alone. None of them was selected after observing its
effect on S1 or S2, because no such observation exists: at the time of writing, the
squad-level instrument has never been run against the archive for this model. The
earlier mean PIT of 0.07 recorded in the first amendment's disclosure remains a
different instrument's number under a different squad, a different weight and a
different shift, and is not evidence about the values fixed here.

### Still open, and recorded rather than chosen

- **`solver_time_limit_seconds` = 10.0 is a wall-clock limit.** The squad comes from a
  MILP solve that will stop at ten seconds regardless of where it is, so under machine
  load a fold could in principle return a different squad than it does on an idle
  machine, and the deterministic seed does not by itself rule that out. The alternative
  control, `solver_deterministic_time_limit`, would change the solve, so it is not
  switched on here. Both values are recorded in the artifact, and a re-run that
  disagrees with a recorded result is caught by the create-once writer rather than
  quietly overwriting it.
- **`worst_fraction` = 0.10 and `points_threshold` = 40.0** are evaluation-config
  knobs that produce summaries neither S1 nor S2 reads. They are pinned at their
  defaults and recorded for completeness, so that a later protocol which does read
  them cannot claim this run's numbers were taken under different ones.

### Found while implementing, and blocking a binding run (2026-08-29)

An adversarial read of the instrument found one thing the second amendment does not
decide, and it stops the protocol from running at all. It is recorded here rather than
settled, because settling it moves the shift and therefore both squad gates.

- **The shift fit's eligible population.** The fit population is built per season:
  the earliest development fold has no prior residual folds at all, the next has one,
  and so on. `min_history_folds = 8` makes the generator refuse any fold with fewer
  than eight, so the first several folds of each fit season cannot be scored as the
  population is currently assembled. Clause 18 says the value "drops the earliest
  eligible folds", which does not say whether those folds simply leave the shift fit,
  or whether the residual history should be widened — across seasons, or with the
  2020-21 season the panel already loads — so that every declared fold is eligible.
  The two readings fit the shift on different populations and produce different
  numbers, so **no binding S1/S2 run is eligible until an amendment names one.**

  The implementation refuses rather than choosing. `fit_frozen_shift` checks the
  population before anything is generated, and raises with the count of ineligible
  folds and the first of them. The tempting repair — skip whichever folds the
  generator rejects — is exactly the failure this programme exists to prevent: it lets
  the crash choose the fit population, after the run has already shown you which folds
  it would drop.

### Recorded as facts about the instrument, not as open decisions

Two properties of the protocol as frozen. Neither is a defect and neither needs a
decision; both belong in the record because a reader of the artifact would otherwise
draw a stronger conclusion than the numbers support.

- **The 37 evaluation readings are not independent of each other.** Clause 9 freezes
  one residual history for the whole evaluation season and clause 8 fixes one seed, so
  every fold draws the same common gameweek shock. The fold-level bootstrap of clause
  22 resamples folds as though they were independent, so its interval understates the
  uncertainty, and S2's decisive count is partly a property of one shared draw. This is
  why clause 22 confines the bootstrap to diagnostics. The artifact records the shared
  draw explicitly.
- **Completeness is checked per gate family, and P1 is measured in cells.** The report
  contract can see that the P1 family was answered; it cannot know how many cells that
  family should have had, because the per-group cells are gated only when a group
  clears its row floor. The merge closes the gap where it has the information — the
  pooled cell is required by name and every recorded cell's verdict is recomputed from
  its own observation — but a reader should know that "P1 answered" is a statement
  about the family, and that the cells are what the recorded artifact happens to carry.

## Third squad-gate amendment (2026-08-30): the frozen shift's fit population

**Written 2026-08-30, still before any target-model S1/S2 measurement exists.** It
settles the one question the second amendment left open and nothing else: which
development folds enter the frozen shift's mean. Thresholds, seeds, scenario count,
quantile, bands and gates are untouched.

27. **A fold with less history than the declared depth does not enter the shift fit.**
    The development population is one chronological chain across the fit seasons, and
    each fold's residual history is the folds of that chain before it. `ScenarioConfig`
    is pre-registered at `min_history_folds = 8`, so the earliest folds of the chain
    have less history than the generator is declared to use. They are a **burn-in**:
    they are excluded from the mean, and the shift is the negated mean gap over the
    remainder. The alternative — widening the residual history so that every fold
    qualifies — is rejected: 2020-21 is loaded as projection and feature history, not
    as residual calibration history, and admitting it would calibrate the shift against
    a population the residual export does not describe.
28. **Eligibility is decided before any scenario is generated.** It is read from the
    fold's own declared history, deterministically, before scenario generation and gate
    computation. It is not discovered by running a fold and catching the generator's
    refusal: a population chosen by which folds happened to raise is a population
    chosen after the fact.
29. **The excluded folds are the earliest of the chain, and there are exactly as many
    of them as the declared depth.** Any other count means the residual export is
    missing folds the population expected, so the run stops and says so rather than
    quietly dropping folds nobody declared. An empty remainder is likewise a refusal,
    never an empty mean.
30. **The remainder is recorded, not implied.** The fold count, first fold id and last
    fold id already required by clause 18 describe the folds that actually entered the
    mean.

The boundaries of the second amendment are unchanged and still bind: cross-season
history may only be carried within the fit seasons, no 2024-25 fold may enter the shift
fit, and 2025-26 is never read.

## Corrective-execution amendment (2026-08-30): residual validation and serialization

The first squad execution stopped without producing an S1 or S2 reading, and without
writing an artifact. It refused during the first eligible development fold, on the
residual history the generator validates before it draws anything.

**The cause is two committed contracts disagreeing, not a measurement.** The residual
export declares `predicted_points_decimals = 9` and rounds `predicted_points`,
`realized_points` and `residual` to nine decimals **independently**, so the identity
`residual = realized_points - predicted_points` can differ by one unit in the ninth
decimal purely as a consequence of that serialization. `validate_residual_history`
required the identity to hold to an absolute tolerance of `1e-10`, an order of
magnitude tighter than the granularity the export is allowed to have. Exactly one row
of 101,447 fell in the gap: `1.0 - 0.449414062 = 0.550585938` against a stored residual
of `0.550585937`. The largest discrepancy anywhere in the export is `1.0e-09`.

31. **Under nine-decimal serialization the accepted absolute tolerance for the residual
    identity is `1e-9`.** That is the smallest difference the declared serialization can
    represent, so it is the smallest difference that can be attributed to rounding
    rather than to the numbers.
32. **Nothing is corrected, recomputed or normalised.** No input value changes, no
    column is recomputed, and the residual export is neither regenerated nor edited —
    it remains bound by its recorded digest `17f88e6e…`, and the recorded P1 artifact
    remains exactly as it was. The tolerance only stops refusing a difference the
    serialization contract is entitled to produce.
33. **A materially inconsistent history is still refused.** The identity is still
    checked on every row; a discrepancy larger than the serialization can explain — at
    `1e-8` and above — still stops the run.
34. **Nothing else moves.** Gates, bands, split, seeds, scenario count, the model, the
    optimizer's settings and the shift's fit population are unchanged, and this
    amendment authorises one corrective execution under exactly the inputs the first
    one used.
