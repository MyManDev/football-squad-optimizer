# Method note: the solver budget and the card rule in the Phase C decision reading

Status: declared on 2026-11-08 before any run. Descriptive measurement; no gate, nothing
promoted, no decision or served model changes whatever the numbers say.

## Why

The paper's decision reading ([`phase_c_gradient_boosting_comparison`](phase_c_gradient_boosting_comparison.md),
[`phase_c_feature_contract_v2_comparison`](phase_c_feature_contract_v2_comparison.md)) solved
every arm under the measurement budget of 5.0 deterministic units, and 41 of the linear arm's
147 solves ended `FEASIBLE` without a proof. A paired difference between two arms is then the
forecast change and the search where either arm stopped unproven, together; nothing measured
so far separates them. The reading also scored every squad with participation read from
minutes alone (`component_decisions._outcomes` carries no `card_participation`), while the
official rule counts a player booked without a minute as having played for the automatic
substitution. The pinned archive holds nine such player-gameweeks in 2021-22 to 2024-25
(Kenneh 2021-22 GW30; Lascelles 2022-23 GW16 and GW19; Nunes 2022-23 GW28; Rodák 2023-24 GW3;
Bettinelli GW18; Felipe GW27; Turner GW31; Sarabia 2024-25 GW8), all with negative points.
Whether any sat in a solved squad is unknown because the records hold scores, not squads.

## What is measured

Three handoff tables are re-exported from the pinned archive at this commit with
`scripts.export_component_oof` under the v2 development scope (184 folds, 2025-26 read as
declared development data, as the records did): the linear control, the boosted pair on v1
features, the boosted pair on v2 features. Each is run through
`scripts.evaluate_phase_c_components --development-contract phase_c_component_oof_development_v2`
against the frozen ridge control on the 147 decision folds of 2021-22 to 2024-25, twice:

| Run | Solver limits | Scoring | Records |
| --- | --- | --- | --- |
| A | deterministic 5.0, wall cap 600 s (the measurement configuration) | official rule with `--card-participation`, and the same squads scored ignoring cards | squads, lineups, captaincy, objective, bound, solver work, both scores per fold per arm |
| B | deterministic 60.0, wall cap 1,800 s | as A | as A |

Run A at 5.0 must reproduce the recorded realized scores of each arm fold for fold when cards
are ignored (same table digest, same seed, same budget); that is the reproduction check, and a
fold that does not reproduce is reported, not repaired. Run B's budget is twelve times the
measurement budget; the wall cap exists so one solve cannot hold the run, and a solve that
reaches it is reported as such.

## What is read from the runs

1. Scoring convention: per arm, the number of folds whose score changes when cards count as
   participation, and the change in the paired candidate-minus-reference mean.
2. Solver budget: per arm, the status counts at 5.0 and at 60.0; per fold, the objective and
   bound at each budget and whether the squad changed; the paired candidate-minus-reference
   mean at each budget, with the recorded 90% season-aware moving-block interval procedure
   (`squadopt.evaluation.statistics`, blocks of 4, 5,000 resamples, seed 0, candidate id
   `paper_solver_budget_<pair>_<budget>`; as run, the id also ends in the scoring convention,
   `_official_card_rule` or `_ignoring_cards`, so each convention has its own resample
   stream, and the record names the id each interval was drawn under).
3. Squad overlap: per fold, the number of shared squad members, shared starters and whether
   the captain is the same between each candidate arm and the linear arm, at each budget; the
   share of the folds that tie on realized points whose squads are identical.

The pairs read are the boosted pair against the linear arm and the boosted pair on v2
features against the boosted pair on v1 features, the two the paper pairs at both levels.

## What is not claimed

No threshold, no verdict on any candidate, no change to the measurement configuration of the
repository (5.0 stays the budget every committed record runs under), nothing served. The
record is development evidence on the same reused folds as the candidate records.

## Where it runs

On the Contabo host's weekly checkout environment (4 vCPU, Python 3.13, the same pinned
constraints), from a clone of the branch that carries this note and the code, writing under
`artifacts/paper_measure/` there; the JSON results come back to the repository under
`docs/research/` as `phase_c_solver_budget_cards.json` with a readout beside it.
