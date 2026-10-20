# Team-match block resampler on the S1 and S2 calibration gates

**Verdict: `candidate_outside_gates`.** Measured, not certified. The candidate sampler
`team_match_block_v1` passes S1 (mean PIT 0.5166 in [0.43, 0.57]) and fails S2 by one fold: the
realized squad score fell below its own scenario tenth percentile in 22 of 137 folds, a rate of
0.1606 against the band [0.04, 0.16]. The foundation sampler, read as the control arm on the
same table, decisions, scenarios and seed, gives 25 of 137 (0.1825). The frozen binding record
gave 28 of 137 (0.2044). The club block thickens the lower tail by three folds on this population
and does not bring it inside the band. Nothing is promoted: `PHASE_E_CALIBRATED_VERSIONS` stays
empty, no probability is published, no product default changes.

Protocol: [team_match_block_sampler_prereg.md](team_match_block_sampler_prereg.md), frozen before
the code. Record: [team_match_block_sampler.json](team_match_block_sampler.json), contract
`phase_d_component_squad_calibration_candidate_v1`, `binding: false`. Written by
`python -m scripts.run_component_squad_calibration --team-match-block` at commit `265e38c3` on a
clean tree (the sampler and runners are commit `6d07dec4`; `265e38c3` adds only the fidelity
record), 2026-10-17 11:53Z to 12:43Z, 3,015 seconds on a four-core Linux container, OR-Tools
9.15.6755, numpy 2.5.2, archive commit `8c97b2ad`. Fidelity precondition:
[the candidate fidelity record](team_match_block_sampler_fidelity.md), verified structurally
before the read (digest `09688767...`). 2025-26 not read. The branch's commits were re-authored on 2026-10-17 under the repository's author identity after the run; each kept its tree, message and dates, so the commit named here is the code that ran under a new id (its tree is `f251dde3ce52b4652fa3226df65eded8fc0f1845`).

## The gates

| Reading | Frozen binding record (foundation, frozen table) | Control arm (foundation, regenerated table) | Candidate (`team_match_block_v1`, regenerated table) |
| --- | --- | --- | --- |
| folds | 137 | 137 | 137 |
| S1: mean PIT, band [0.43, 0.57] | 0.5147, pass | 0.5197, pass | 0.5166, pass |
| S2: realized below q10, band [0.04, 0.16] | 28 of 137, 0.2044, fail | 25 of 137, 0.1825, fail | 22 of 137, 0.1606, fail |
| mean q10 of the squad score | not recorded | 48.91 | 47.98 |
| mean scenario standard deviation | not recorded | 11.53 | 12.53 |

Point estimates decide, as the binding protocol says. 0.1606 is above 0.16 by 0.0006, which is
one fold of 137; the band is inclusive and the tolerance is 1e-9, so the gate fails. It is
reported as it fell and is not re-run.

### Both PIT tails (descriptive)

The brief asked for the upper-tail rate beside the lower. Counted from the per-fold PIT of each
arm over the same 137 folds:

| PIT tail | Frozen binding record | Control arm | Candidate |
| --- | --- | --- | --- |
| at or above 0.95 (realized score at or above the scenario 95th percentile) | 14 (0.1022) | 16 (0.1168) | 11 (0.0803) |
| at or below 0.05 | 19 (0.1387) | 19 (0.1387) | 16 (0.1168) |

Both tails are heavier than the nominal 0.05 under every arm, and the block thins both: the
candidate's distribution is wider on both sides, not shifted.

### Per season (descriptive)

| Season | Folds | Candidate mean PIT | Candidate below q10 | Control mean PIT | Control below q10 |
| --- | --- | --- | --- | --- | --- |
| 2021-22 | 27 | 0.5006 | 5 (0.1852) | 0.5055 | 6 (0.2222) |
| 2022-23 | 36 | 0.6084 | 2 (0.0556) | 0.6118 | 3 (0.0833) |
| 2023-24 | 37 | 0.4396 | 11 (0.2973) | 0.4373 | 12 (0.3243) |
| 2024-25 | 37 | 0.5159 | 4 (0.1081) | 0.5228 | 4 (0.1081) |

The season pattern is the one `phase2_tail_diagnostic` found: 2023-24 fails S2 under either
sampler, 2022-23 and 2024-25 sit inside the band under either, and the club block moves one fold
in each of three seasons.

### Paired per-fold differences, candidate minus control (descriptive)

90% season-aware moving-block bootstrap, blocks of four folds within a season, 2,000 resamples,
seed 0. It decides nothing; the gates are read on point estimates.

| Quantity | Mean | 90% interval |
| --- | --- | --- |
| below-q10 indicator | -0.0219 (three folds of 137) | [-0.0438, 0.0000] |
| PIT | -0.0031 | [-0.0061, -0.0002] |

Five folds change their tail flag: four leave the tail (`2021-22-gw19`, `2022-23-gw37`,
`2023-24-gw38`, `2024-25-gw27`) and one enters it (`2024-25-gw37`).

## Why the control arm is not the frozen record

Step 1 of the protocol regenerated the Phase C v1 table on a clean tree and found a different
table digest with the same roster and the same row structure (details in the pre-registration).
Both arms were therefore read on the regenerated table. Against the frozen record, the control
arm reproduces the realized score of 127 of 137 frozen decisions exactly; ten full-pool decisions
differ, as the solver's incumbent moves with the regenerated predictions (44 of 147 solves ended
FEASIBLE, 103 OPTIMAL). The per-fold PIT agrees exactly on 8 folds; the signed mean difference,
control minus frozen, is +0.0050 (0.5197 against 0.5147), the mean absolute per-fold difference
is 0.0156 and the largest is 0.40, since the residual pools differ in their values; the tail
flag differs on 5 folds, which is the 28 against 25. The frozen verdict (S1 pass, S2 fail) is reproduced in kind,
not in count. The candidate's reading is a reading on the regenerated table, beside its own
control; it is not a reading on the binding table, and this record says so.

## What the block changed in the draws

| Diagnostic (mean over 137 folds) | Candidate | Control |
| --- | --- | --- |
| within-club Pearson correlation of scenario points, same-club pairs of the squad (7.7 pairs per squad on average, every squad has at least one) | 0.1805 (p10 0.113, p50 0.167, p90 0.252) | 0.0037 (p10 -0.012, p50 0.003, p90 0.020) |
| scenario standard deviation ratio, candidate over control | 1.0875 (min 0.94, max 1.43) | 1 |
| q10 of the squad score, candidate minus control | -0.93 points | 0 |
| history folds per draw | 77.0 | 77.0 |
| club-week blocks per history fold | 18.9 | not applicable |
| rows per block | 14.4 | not applicable |
| target clubs per squad | 9.1 | not applicable |
| fixture-count fallback rate over scenario-club cells | 0.0897 (33 folds above zero, largest 0.757: double-gameweek clubs whose history holds few two-fixture blocks) | not applicable |
| position fallback rate over scenario-player cells | 0.0090 | not applicable |
| mixed-fixture blocks, mixed-fixture target clubs, blank-club cells | 0, 0, 0 | not applicable |

The block does what it was built to do: same-club squad members' scenario points now co-move
(0.18 against 0.00), the squad distribution widens by 8.75% on average and its tenth percentile
drops by 0.93 points. One design note on that 0.18: rows within a position group are drawn with
replacement, so two same-club same-position squad members can take the identical source row in
a scenario, and part of the within-club correlation is row identity rather than inherited
co-movement. That buys three folds of lower tail. The remaining gap to the band (one
fold here, and 2023-24 at 0.2973 under either sampler) is not within-club co-movement.

## What this record is and is not

- A development measurement on the frozen Phase D population and gates, on a regenerated v1
  table, with a verified fidelity precondition. It is not the binding verdict and does not touch
  the binding record.
- `locked_holdout_accessed: false`. 2025-26 is excluded by the population and refused by the v1
  export.
- The noise floor is stated as the repository requires: an effect smaller than 1.5 points per
  gameweek is not certified. This record makes no points claim; its gates are the S1 and S2
  bands, and the candidate is outside S2.
- Not measured: opponent pairing, the captain's second copy, dispersion scales, location shifts,
  multi-week paths. The one-fold distance to the band invites none of them; a next step needs its
  own pre-registration.
