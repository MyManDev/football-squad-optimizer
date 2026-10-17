# Team-match block sampler: fidelity diagnostic

**Diagnostic only. No gate, no threshold, nothing promoted or tuned.** The sampler fidelity
diagnostic of `docs/phase_d_component_fidelity_prereg.md`, run on the candidate sampler
`team_match_block_v1` as the precondition the
[team-match block pre-registration](team_match_block_sampler_prereg.md) requires before its
calibration run. Record: [team_match_block_sampler_fidelity.json](team_match_block_sampler_fidelity.json),
contract `phase_d_component_fidelity_candidate_v1`, `binding: false`.

Written by `python -m scripts.measure_component_fidelity --team-match-block` at commit
`3d52acd1` on a clean tree, pinned to the regenerated Phase C v1 table (table
`6dd22797...`, roster `3ef0c571...`, manifest `66096a7c...`, produced at commit `1079ba64`;
see the pre-registration for why the table digest differs from the binding record's).
`ScenarioConfig()` defaults: 1,000 scenarios, seed 0, `min_history_folds` 8. Population: 147
folds, 9 burn-in folds excluded, 138 measured, 95,323 fold-player observations, 2021-22 to
2024-25. 2025-26 not read. No warnings.

## The five differences, sampled minus predicted, pooled over fold-player observations

The frozen foundation record (`docs/phase_d_component_fidelity.json`, the same diagnostic on
the frozen table with the same row structure) is quoted beside the candidate for orientation.
Exact agreement is not expected under either sampler: the residual pool is empirical and is not
required to have mean zero, and minutes carry the ceiling and the one-minute floor.

| Metric | Candidate signed | Candidate absolute | Foundation signed | Foundation absolute |
| --- | --- | --- | --- | --- |
| appearance | +0.00005 | 0.0081 | -0.00005 | 0.0081 |
| points, unconditional | +0.0055 | 0.0675 | -0.0013 | 0.0482 |
| minutes, unconditional | -0.986 | 1.902 | -1.441 | 1.840 |
| minutes, conditional on appearance | -0.242 | 4.298 | -1.407 | 2.995 |
| points, conditional on appearance | +0.031 | 0.222 | -0.002 | 0.181 |

Candidate levels: appearance 0.4105 sampled against 0.4104 predicted; unconditional points
1.2068 against 1.2013; conditional minutes 57.45 against 57.69; conditional points 2.401
against 2.370.

Per-fold means of the candidate (138 folds): conditional points mean +0.032 (p10 +0.005, p90
+0.073, range -0.033 to +0.163); conditional minutes mean -0.240 (p10 -0.78, p90 +0.27);
unconditional minutes mean -0.991 (range -1.67 to -0.07); appearance mean 0.0000.

## Counts

| Count | Candidate | Foundation |
| --- | --- | --- |
| cells | 95,323,000 | 95,323,000 |
| appeared cells | 39,127,804 | 39,117,876 |
| floor-engaged cells (upper bound) | 1,057,730 (rate 0.0270) | 1,328,649 (rate 0.0340) |
| ceiling-engaged cells | 8,978,565 | 8,922,482 |
| direct-control rows excluded | 1,317 | 1,317 |
| players never appearing | 0 | 0 |

## Reading

The appearance stream is shared with the foundation seed for seed, so the appearance difference
is the same size. The candidate's conditional points sit 0.03 above the prediction on average
where the foundation's sat on it: a club-week block draws a player's residual from a block of
the same position, and the positional residual pool is not mean zero fold by fold. The
conditional minutes gap narrows (from -1.41 to -0.24) and the floor engages less often (2.7%
against 3.4% of appeared cells): a same-position row's minutes residual is less often far below
a player's own expectation than a row drawn from the whole fold. The absolute differences per
fold-player are larger under the candidate on every conditional metric, which is what a draw
from a smaller, more specific block does to a per-player mean over 1,000 scenarios.

None of this is a gate and none of it is read as one. The calibration run that follows
verifies this record structurally (contract, digests, sampler, configuration, population) and
reads S1 and S2 on its own frozen population.
