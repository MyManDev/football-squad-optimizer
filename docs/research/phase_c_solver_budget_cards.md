# Solver budget and card rule in the Phase C decision reading: readout

Record: [`phase_c_solver_budget_cards.json`](phase_c_solver_budget_cards.json), written by
`scripts.summarize_solver_budget_cards` from the evaluations of the
[method note](phase_c_solver_budget_cards_method.md). Descriptive; no gate, nothing promoted,
the measurement configuration of the repository (5.0 deterministic units) unchanged.

Status: run A (budget 5.0) completed on 2026-11-08; run B (budget 60.0) is running and the
record names it under `budgets_absent` until its three evaluations are summarized. Every
number below is from run A.

## Where it ran

A clean clone of branch `measure/paper-solver-budget-cards` on a 4 vCPU Linux host, at low
priority beside the live backend: Python 3.13.18, pandas 3.0.5, scikit-learn 1.9.0, OR-Tools
9.15.6755, the pinned archive. The three handoff tables were exported there for the four
decision seasons (`--seasons 2021-22,2022-23,2023-24,2024-25`, as the records' reproduce
commands state). The evaluations took 3,835 s (linear), 2,547 s (boosted pair, v1 features)
and 2,520 s (wider contract, v2 features), one search worker, seed 0, both arms.

## Reproduction at 5.0

| Table | Table digest equals the record's | Fold scores reproduced (cards ignored) | Folds differing | Rerun statuses, candidate arm |
| --- | --- | --- | --- | --- |
| linear components | no (`20eb4776…` against `13330e61…`) | 135 of 147 | 12, every one `FEASIBLE` in the rerun; sum of differences −8 points (−0.054 a fold); rerun mean 63.36 against the recorded 63.42 | 103 proven, 44 feasible (record: 106 and 41) |
| boosted pair, v1 features | yes | 147 of 147 | none | 147 proven |
| wider contract, v2 features | yes | 147 of 147 | none | 147 proven |

The ridge control, solved beside every table, ended 116 proven and 31 feasible (record: 117
and 30), with a mean of 58.57 realized points against the recorded 58.52; the record holds
both arms' status counts and means under `arms/<table>_b5.0`. The two boosted
tables re-exported byte for byte and every decision came back the same; the ridge table did
not re-export byte for byte (a linear fit on a different interpreter and numerical library),
and every fold whose score moved is a fold the solver stopped at its budget. The 103 folds the
solver proved reproduce exactly. The 12 folds are listed in the record under
`reproduction_at_5_0/linear_dec/folds_differing`.

## The card rule

Scoring every solved squad under the official rule, where a player booked without a minute
counts as having played for the automatic substitution, changed the realized score of **no
fold** in any of the six arm-tables (147 folds each, both arms). None of the nine booked
zero-minute player-gameweeks of the four decision seasons was a starter, or a bench player
reached by the automatic substitution, in a solved squad (a booked player left unused on the
bench changes nothing and is not detected by this measurement). The paired
means are therefore identical under the two conventions; the intervals differ in the second
decimal only because each convention has its own bootstrap candidate id (boosted pair minus
linear: `[-2.49, 1.03]` official against `[-2.54, 1.04]` ignoring cards).

## Paired readings and squad overlap at 5.0

| Pair | Mean | 90% interval | W/T/L | Recorded mean and interval | Shared squad members of 15 (mean) | Shared starters of 11 (mean) | Same captain | Identical squads | Ties | Ties with identical squads |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| boosted pair minus linear components | −0.694 | [−2.49, 1.03] | 74/5/68 | −0.748, [−2.66, 1.05] | 5.85 | 4.76 | 56 of 147 | 1 of 147 | 5 | 1 |
| wider contract minus boosted pair | −0.204 | [−1.81, 1.05] | 69/10/68 | −0.204, [−1.80, 1.06] | 9.30 | 7.35 | 100 of 147 | 2 of 147 | 10 | 1 |

The wider-contract pair reproduces the recorded mean exactly because both of its tables
reproduced fold for fold; the boosted-pair-minus-linear mean moved from −0.748 to −0.694 with
the 12 linear folds. A tie on realized points is almost never an identical squad: of the 15
tied folds across the two pairs, 2 have the same fifteen players. Two forecasts a few
hundredths of MAE apart share about six of fifteen squad members (boosted pair against
linear) and about nine (wider contract against the boosted pair); the histogram of shared
members is in the record under `pairs/<pair>/budget_5.0_overlap`.

## What is not claimed

No verdict on any candidate changes. The 60.0 budget (run B) is what separates the forecast's
effect from the search's on the unproven folds; until it is summarized the record states only
run A, and the 12 linear folds are reported as differing, not repaired.
