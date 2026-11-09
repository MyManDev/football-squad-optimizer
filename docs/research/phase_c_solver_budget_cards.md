# Solver budget and card rule in the Phase C decision reading: readout

Record: [`phase_c_solver_budget_cards.json`](phase_c_solver_budget_cards.json), written by
`scripts.summarize_solver_budget_cards` from the evaluations of the
[method note](phase_c_solver_budget_cards_method.md). Descriptive; no gate, nothing promoted,
the measurement configuration of the repository (5.0 deterministic units) unchanged.

Status: run A (budget 5.0) completed on 2026-11-08 and run B (budget 60.0) on 2026-11-09;
the record holds both budgets (`budgets_present`), nothing is absent, and since 2026-11-09 it
also holds every fold's decision for every arm at both budgets (`decisions`), so each summary
below can be recomputed from the record alone.

## Where it ran

A clean clone of branch `measure/paper-solver-budget-cards` on a 4 vCPU Linux host, at low
priority beside the live backend: Python 3.13.18, pandas 3.0.5, scikit-learn 1.9.0, OR-Tools
9.15.6755, the pinned archive. The three handoff tables were exported there for the four
decision seasons (`--seasons 2021-22,2022-23,2023-24,2024-25`, as the records' reproduce
commands state). One search worker, seed 0, both arms, every evaluation:

| Table | Run A, 5.0 | Run B, 60.0 (wall cap 1,800 s) |
| --- | --- | --- |
| linear components | 3,835 s | 13,390 s |
| boosted pair, v1 features | 2,547 s | 6,544 s |
| wider contract, v2 features | 2,520 s | 6,546 s |

No solve of run B reached the wall cap: every evaluation document records the deterministic
limit as the binding one, and every unproven solve stopped at 60.0 units of work.

## Reproduction at 5.0

| Table | Table digest equals the record's | Fold scores reproduced (cards ignored) | Folds differing | Rerun statuses, candidate arm |
| --- | --- | --- | --- | --- |
| linear components | no (`20eb4776…` against `13330e61…`) | 135 of 147 | 12, every one `FEASIBLE` in the rerun; sum of differences −8 points (−0.054 a fold); rerun mean 63.36 against the recorded 63.42 | 103 proven, 44 feasible (record: 106 and 41) |
| boosted pair, v1 features | yes | 147 of 147 | none | 147 proven |
| wider contract, v2 features | yes | 147 of 147 | none | 147 proven |

The ridge control, solved beside every table, ended 116 proven and 31 feasible (record: 117
and 30), with a mean of 58.57 realized points against the recorded 58.52; the record holds
both arms' status counts and means under `arms/<table>_b<budget>`. The two boosted
tables re-exported byte for byte and every decision came back the same; the linear-component
handoff table did not re-export byte for byte (a linear fit on a different interpreter and
numerical library), and every fold whose score moved is a fold the solver stopped at its
budget. The 103 folds the solver proved reproduce exactly. The 12 folds are listed in the
record under `reproduction_at_5_0/linear_dec/folds_differing`.

## Rescoring under the card rule

Rescoring the fixed squads of the four arms re-evaluated here (the linear components, the
boosted pair, the wider contract and the ridge control beside them) under the official rule,
where a player booked without a minute counts as having played for the automatic
substitution, changed the realized score of **no fold** in any of the twelve arm-tables
(three tables, two arms, two budgets; 147 folds each). So for these arms the scoring
correction cost nothing at the decision level. The paired means are therefore identical under
the two conventions at both budgets; the intervals differ in the second decimal only because
each convention has its own bootstrap candidate id (boosted pair minus linear at 5.0:
`[-2.49, 1.03]` official against `[-2.54, 1.04]` ignoring cards).

Two limits of this check. It covers the arms whose squads were recorded here, not the
points-only, regime-gated and mixture arms of the paper, whose records hold fold scores and no
squads; a general statement about those arms needs their own re-evaluation. And it measures
the scoring correction on fixed squads, not the modelling assumption behind it: a forecast
that carried the dropped term `(1 − p) E[Y | A = 0, x]` could change the expected points and
with them the squads selected, and rescoring fixed squads says nothing about that effect. A
booked player left unused on the bench changes nothing under either convention and is not
detected by this measurement.

## The second budget: 5.0 to 60.0

Twelve times the measurement budget, per arm, over the same 147 folds (record block
`budget/<table>/{candidate,ridge_control}`):

| Arm | Statuses at 5.0 | Statuses at 60.0 | Squads changed | Starting elevens changed | Captains changed | Objective gain, mean / max (expected points) | Gap to bound left at 5.0 on its unproven folds, mean / max | Realized score: folds changed, mean change | Mean realized score 5.0 → 60.0 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| linear components | 103 / 44 | 136 / 11 | 16 | 13 | 0 | 0.011 / 0.305 | 5.32 / 8.98 | 13, −0.163 (sum −24) | 63.36 → 63.20 |
| ridge control (same in all three evaluations) | 116 / 31 | 140 / 7 | 5 | 4 | 0 | 0.007 / 0.414 | 5.92 / 8.55 | 4, +0.007 (sum +1) | 58.57 → 58.58 |
| boosted pair, v1 features | 147 / 0 | 147 / 0 | 0 | 0 | 0 | 0 / 0 | none unproven | 0, 0 | 62.67 → 62.67 |
| wider contract, v2 features | 147 / 0 | 147 / 0 | 0 | 0 | 0 | 0 / 0 | none unproven | 0, 0 | 62.46 → 62.46 |

Every fold proven at both budgets returned the same fifteen players (103 of the linear arm's,
116 of the control's, all 147 of each boosted arm's;
`proven_at_both_budgets_squad_changed_folds` is 0 everywhere). The gap the 5.0 budget left
between incumbent and bound on its unproven folds (about five to nine expected points) is
almost entirely bound, not solution: twelve times the work raised the objective by 0.011
expected points a fold on the linear arm (at most 0.305 on one fold) and by 0.007 on the
control, proved 33 and 24 more folds, and moved 16 and 5 squads. The realized score of the
squads moved by −0.163 a fold on the linear arm and +0.007 on the control, so the longer
search did not raise realized points. Both boosted arms were proven on every fold at 5.0 and
used at most 5.75 and 3.56 units at 60.0; their decisions are identical at the two budgets.

## Paired readings and squad overlap at both budgets

| Pair | Budget | Mean | 90% interval | W/T/L | Recorded mean and interval | Shared squad members of 15 (mean) | Shared starters of 11 (mean) | Same captain | Identical squads | Ties | Ties with identical squads |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| boosted pair minus linear components | 5.0 | −0.694 | [−2.49, 1.03] | 74/5/68 | −0.748, [−2.66, 1.05] | 5.85 | 4.76 | 56 of 147 | 1 of 147 | 5 | 1 |
| boosted pair minus linear components | 60.0 | −0.531 | [−2.35, 1.23] | 76/5/66 | | 5.84 | 4.73 | 56 of 147 | 1 of 147 | 5 | 1 |
| wider contract minus boosted pair | 5.0 | −0.204 | [−1.81, 1.05] | 69/10/68 | −0.204, [−1.80, 1.06] | 9.30 | 7.35 | 100 of 147 | 2 of 147 | 10 | 1 |
| wider contract minus boosted pair | 60.0 | −0.204 | [−1.78, 1.07] | 69/10/68 | | 9.30 | 7.35 | 100 of 147 | 2 of 147 | 10 | 1 |

The wider-contract pair is the same at both budgets because neither of its tables has an
unproven fold; its interval ends differ between the budgets only because the bootstrap stream
is seeded from a candidate id that names the budget, a Monte Carlo difference and not a solver
one. The boosted-pair-minus-linear mean moved from −0.694 to −0.531 only because the linear
arm lost 24 realized points over its 13 moved folds; the boosted pair's squads did not change.
Season means at 60.0 are −3.65, +0.61, +2.92 and −1.97 for 2021-22 to 2024-25 (at 5.0: −3.59,
+0.22, +2.27, −1.65), the same sign pattern. A tie on realized points is almost never an
identical squad: of the 15 tied folds across the two pairs at either budget, 2 have the same
fifteen players. Two forecasts a few hundredths of MAE apart share about six of fifteen squad
members (boosted pair against linear) and about nine (wider contract against the boosted
pair); the histograms of shared members are in the record under
`pairs/<pair>/budget_<budget>_overlap`.

## What the budget reading does and does not say

Increasing the deterministic budget from 5.0 to 60.0 changed the boosted-pair-minus-linear
mean by +0.163 points a gameweek and the wider-contract pair not at all. That is the
sensitivity of the paired readings to the tested budget increase. It is not an upper bound on
what the search still contributes to the paired difference: 11 of the linear arm's solves and
7 of the control's were still unproven at 60.0, and the solver's bound is on the surrogate
objective in expected points, which does not bound the realized points a different incumbent
would have scored. Closing the question needs every solve run to proof. No verdict on any
candidate changes, and the 12 linear folds of the reproduction check are reported as
differing, not repaired.

## Provenance and reproduction

The record was produced in two stages, which it names under `produced_by`, `inputs` and
`raw_evaluation_documents`.

**Stage 1, the runner.** Each of the six evaluation documents names `repository_commit`
`5d5e6fbd` (this branch, the commit that fixed the serialization of recorded decisions). The
driver on the host exported the three decision-season tables and ran the six evaluations in
this form, from a clone of this branch with `PYTHONPATH=src:.` and the pinned archive:

```bash
python -m scripts.export_component_oof --archive-root <archive> --development-scope v2 \
    --season-weighting equal --seasons 2021-22,2022-23,2023-24,2024-25 \
    --output-dir artifacts/paper_measure/<table>            # plus, for the boosted tables,
                                                            # --estimator gradient_boosting
                                                            # [--feature-contract v2]
python -m scripts.evaluate_phase_c_components --table <table>.csv --manifest <table>.manifest.json \
    --roster <table>.roster.csv --producer-environment <table>.environment.json \
    --archive-root <archive> --development-contract phase_c_component_oof_development_v2 \
    --solver-deterministic-budget <5.0 | 60.0> --solver-wall-cap-seconds <600 | 1800> \
    --card-participation --record-decisions \
    --json-output artifacts/paper_measure/eval_<table>_b<budget>.json
```

The `<table>` names are `linear_dec`, `gbm_v1_dec` and `gbm_v2_dec`; the environment file
beside each table carries its digest, the export commit and the exporter's package versions.
The six documents, kept outside the repository (about 411 kB each), and their SHA-256 with
CRLF read as LF:

| Document | Bytes | SHA-256 |
| --- | --- | --- |
| `eval_linear_dec_b5.0.json` | 411,551 | `4bb2c31bee5f7411a2064bfcc65945721dfdc20e220e10d0db931b7401f14afe` |
| `eval_linear_dec_b60.0.json` | 411,459 | `f7c49ccee11ed8bfbac8445dcf273fe14764da18316e3fbf6c7732f5973addbc` |
| `eval_gbm_v1_dec_b5.0.json` | 411,611 | `a6345c58dc4bb2a08118b68a8d4498073007103278853ef3a4131dfc1cc4d1c9` |
| `eval_gbm_v1_dec_b60.0.json` | 411,579 | `b036c799893bcf5a80b56ff881ef1ec8af6ead38fb1a660103da5d6a139bebe5` |
| `eval_gbm_v2_dec_b5.0.json` | 411,632 | `d91fea91e41615df365e6c900066f364b24f699cb85259a6f1dc95f3b554d900` |
| `eval_gbm_v2_dec_b60.0.json` | 411,598 | `7cf86c6748b731068d7dccad078996fea7d6259fbedf5b738286935edae6a8b6` |

**Stage 2, the summarizer.** `scripts/summarize_solver_budget_cards.py` at commit `d582b626`
of this branch (pull request #1369) read the six documents and wrote the record:

```bash
python -m scripts.summarize_solver_budget_cards --inputs-dir artifacts/paper_measure \
    --output docs/research/phase_c_solver_budget_cards.json
```

The summarizer at `5d5e6fbd` wrote an interim form of this record without the second budget,
the per-arm blocks and the fold decisions; the record committed here is the one the summarizer
at `d582b626` writes, and `produced_by/summarizer_sha256` is the digest of that file, so the
two stages are told apart by the record itself. Rerunning stage 2 on the six documents above
reproduces the committed record byte for byte.

**What the record holds per fold.** Under `decisions/<table>_b<budget>/{candidate,ridge_control}/<fold>`:
the fifteen (`squad`) and the starting eleven (`starting_xi`), each as sorted player codes on
one line, the bench in its order (`bench_order`), `captain_id` and `vice_captain_id`,
`solver_status`, `objective_value` and `best_objective_bound` in expected points,
`deterministic_time_used`, and `realized_score` under the official card rule beside
`realized_score_ignoring_cards`. The paper package's extractor writes these out as one CSV and
recomputes from them every status count, mean, card-rule count, budget block, paired reading
(intervals included, under the candidate ids the record names) and overlap block above.
