# Joint team-match sampler: fidelity diagnostic

**Diagnostic only. No gate, no threshold, nothing promoted or tuned.** The sampler fidelity
diagnostic of `docs/phase_d_component_fidelity_prereg.md`, run on the candidate sampler
`team_match_joint_v1` as the precondition the [joint sampler pre-registration](moe_sampler_prereg.md)
requires before its calibration run. Record: [moe_sampler_fidelity.json](moe_sampler_fidelity.json),
contract `phase_d_component_fidelity_candidate_v1`, `binding: false`.

Written by `python -m scripts.measure_component_fidelity --team-match-joint` at commit
`650e6371` on a clean tree, pinned to the frozen binding Phase C v1 table itself (table
`b05f10c3...`, roster `3ef0c571...`, manifest `1a06b69a...`, the digests the binding record
pins; the files sit on the owner's machine and were verified by digest before the run).
`ScenarioConfig()` defaults: 1,000 scenarios, seed 0, `min_history_folds` 8. Population: 147
folds, 9 burn-in folds excluded, 138 measured, 95,323 fold-player observations, 2021-22 to
2024-25. 2025-26 not read. No warnings. Generated 2026-10-17 16:49Z; the whole run took about
one minute on the owner's Windows machine.

## The five differences, sampled minus predicted, pooled over fold-player observations

The frozen foundation record (`docs/phase_d_component_fidelity.json`) was measured on this same
table, so it is a direct comparison here. The #1145 block candidate record
(`team_match_block_sampler_fidelity.json`) was measured on a regenerated table with a different
digest and is quoted for orientation only.

| Metric | Joint signed | Joint absolute | Foundation signed | Foundation absolute | Block candidate signed |
| --- | --- | --- | --- | --- | --- |
| appearance | -0.00391 | 0.0115 | -0.00005 | 0.0081 | +0.00005 |
| points, unconditional | -0.0105 | 0.0698 | -0.0013 | 0.0482 | +0.0055 |
| minutes, unconditional | -1.374 | 2.166 | -1.441 | 1.840 | -0.986 |
| minutes, conditional on appearance | -0.962 | 6.344 | -1.407 | 2.995 | -0.242 |
| points, conditional on appearance | +0.0156 | 0.2444 | -0.0023 | 0.1810 | +0.031 |

Joint levels: appearance 0.4065 sampled against 0.4104 predicted; unconditional points 1.1908
against 1.2013; conditional minutes 56.73 against 57.69; conditional points 2.385 against 2.370.

Per-fold means of the joint candidate (138 folds): appearance -0.0040 (p10 -0.0060, p90
-0.0025, range -0.0085 to -0.0017, every fold below zero); conditional minutes -0.931 (p10
-1.42, p90 -0.13); unconditional minutes -1.380 (range -2.18 to -0.54); conditional points
+0.018 (p10 -0.015, p90 +0.075); unconditional points -0.010 (p10 -0.022, p90 -0.000).

## Counts

| Count | Joint | Foundation |
| --- | --- | --- |
| cells | 95,323,000 | 95,323,000 |
| appeared cells | 38,750,016 | 39,117,876 |
| floor-engaged cells (upper bound) | 1,120,130 (rate 0.0289) | 1,328,649 (rate 0.0340) |
| ceiling-engaged cells | 8,985,665 (0.2319 of appeared) | 8,922,482 (0.2281) |
| direct-control rows excluded | 1,317 | 1,317 |
| players never appearing | 0 | 0 |

## Reading

The appearance is no longer drawn against the prediction alone: it is inherited from the source
row's observed appearance through its latent uniform, so the sampled level equals the predicted
one only where the source rows' appearance model is calibrated. On this table's component rows
(read from the table, not from the record) the realized appearance rate sits below the
predicted probability in the bottom decile (predicted 0.076 against realized 0.041 on 39,347
rows) and above it in the middle deciles, and the pooled
pass-through is -0.0039, every fold in the same direction: 0.94% fewer appeared cells than the
foundation draws (38,750,016 against 39,117,876). That is what the
pre-registration said this construction would do, and the calibration read measures whether it
matters at squad level; nothing here is a gate.

The conditional minutes gap narrows from -1.41 to -0.96 and the floor engages less often (2.9%
against 3.4% of appeared cells), for the reason the block candidate gave: a same-position row of
a club-week block is less often far below a player's own minutes expectation than a row from the
whole fold. The per-player absolute differences are larger on every conditional metric (6.3
minutes against 3.0), which is what a draw from a smaller, more specific block does to a
per-player mean over 1,000 scenarios, compounded here by the appearance varying with the block.
Conditional points sit +0.016 above the prediction (the block candidate: +0.031); unconditional
points -0.010, the appearance shortfall carried through.

None of this is a gate and none of it is read as one. The calibration run that follows verifies
this record structurally (contract, digests, sampler, configuration, population) and reads S1 and
S2 on its own frozen population.
