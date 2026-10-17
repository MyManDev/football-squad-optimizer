# Joint team-match sampler on the S1 and S2 calibration gates

**Verdict: `candidate_within_gates`.** Measured, not certified. The candidate sampler
`team_match_joint_v1` passes S1 (mean PIT 0.5207 in [0.43, 0.57]) and passes S2: the realized
squad score fell below its own scenario tenth percentile in 21 of 137 folds, a rate of 0.1533
against the band [0.04, 0.16]. The margin is one fold: 22 would be 0.1606 and outside. The
foundation sampler, read as Control A on the same frozen table, decisions, scenarios and seed,
gives 28 of 137 (0.2044), reproducing the frozen binding record's count; the #1145 block sampler
as Control B gives 23 of 137 (0.1679). G1, G2 and G3 of the pre-registration hold, so the
candidate meets the pin condition's sampler clause; G4 (descriptive) does not, by the mean PIT
clause alone. Nothing is promoted: `PHASE_E_CALIBRATED_VERSIONS` stays empty, no probability is
published, no product default changes; a pin is the owner's separate, reviewed change.

Protocol: [moe_sampler_prereg.md](moe_sampler_prereg.md), frozen before the code (commit
`122350cf`); nothing in it changed after. Record: [moe_sampler.json](moe_sampler.json), contract
`phase_d_component_squad_calibration_candidate_v1`, `binding: false`. Written by
`python -m scripts.run_component_squad_calibration --team-match-joint` at commit `7283993e` on a
clean tree (the sampler is commits `0a4f88ee` and `650e6371`; the later commits add only the
fidelity record and its twin), 2026-10-17 16:50Z to 17:28Z, 2,311 seconds on the owner's
Windows 11 machine (32 logical CPUs, shared with three other measurement runs), Python 3.13.5,
numpy 2.5.2, pandas 3.0.5, OR-Tools 9.15.6755, archive commit `8c97b2ad`. Solver: 106 of 147
decisions OPTIMAL, 41 FEASIBLE under the deterministic 5.0 budget. Fidelity precondition:
[the candidate fidelity record](moe_sampler_fidelity.md), verified structurally before the read
(digest `479bddad...`). 2025-26 not read.

## The table

Every arm was read on the frozen binding Phase C v1 table itself (table `b05f10c3...`, roster
`3ef0c571...`, manifest `1a06b69a...`), not on a regenerated one as #1145 had to. Against the
frozen binding record, Control A reproduces the realized score and the PIT of 127 of 137
decisions exactly and the tail flag of all 137; the same ten full-pool decisions move with the
solver's incumbent that #1145 reported, which is why Control A's mean PIT is 0.5209 against the
record's 0.5147 while its tail count is the record's 28.

## The gates

| Reading | Frozen binding record (foundation) | Control A (foundation) | Control B (`team_match_block_v1`) | Candidate (`team_match_joint_v1`) |
| --- | --- | --- | --- | --- |
| folds | 137 | 137 | 137 | 137 |
| S1: mean PIT, band [0.43, 0.57] | 0.5147, pass | 0.5209, pass | 0.5186, pass | 0.5207, pass |
| S2: realized below q10, band [0.04, 0.16] | 28 (0.2044), fail | 28 (0.2044), fail | 23 (0.1679), fail | 21 (0.1533), pass |
| PIT at or above 0.95 | 14 (0.1022) | 16 (0.1168) | 12 (0.0876) | 14 (0.1022) |
| PIT at or below 0.05 | 19 (0.1387) | 20 (0.1460) | 18 (0.1314) | 18 (0.1314) |
| mean q10 of the squad score | not recorded | 48.98 | 47.92 | 47.81 |
| mean scenario standard deviation | not recorded | 11.43 | 12.57 | 12.52 |

Point estimates decide, as the binding protocol says. The band is inclusive with tolerance
1e-9; 0.1533 is inside it by one fold. It is reported as it fell and is not re-run.

### The gate clauses

| Clause | Value | Holds |
| --- | --- | --- |
| G1: S1 mean PIT in [0.43, 0.57] | 0.5207 | yes |
| G2: S2 lower-tail rate in [0.04, 0.16] | 21 of 137, 0.1533 | yes |
| G3 against Control A: `abs(mean PIT - 0.5)` not greater | 0.0207 against 0.0209 | yes |
| G3 against Control A: lower-tail count not greater | 21 against 28 | yes |
| G4 against Control B (descriptive): `abs(mean PIT - 0.5)` not greater | 0.0207 against 0.0186 | no |
| G4 against Control B (descriptive): lower-tail count not greater | 21 against 23 | yes |

### Per season (descriptive)

| Season | Folds | Candidate mean PIT | Candidate below q10 | Control A mean PIT | Control A below q10 | Control B mean PIT | Control B below q10 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2021-22 | 27 | 0.5010 | 6 (0.2222) | 0.5004 | 7 (0.2593) | 0.4965 | 7 (0.2593) |
| 2022-23 | 36 | 0.6130 | 1 (0.0278) | 0.6079 | 4 (0.1111) | 0.6118 | 1 (0.0278) |
| 2023-24 | 37 | 0.4253 | 11 (0.2973) | 0.4239 | 13 (0.3514) | 0.4239 | 12 (0.3243) |
| 2024-25 | 37 | 0.5406 | 3 (0.0811) | 0.5481 | 4 (0.1081) | 0.5388 | 3 (0.0811) |

The season pattern is the one every sampler shows: 2023-24 fails S2 under all three (0.2973
under the candidate), 2022-23 sits at the bottom of the band under the two block samplers and
below it for the tail (0.0278), and the pooled pass is the sum of a season above the band and
seasons below it. The pooled reading decides; the seasons cannot overturn it.

### Paired per-fold differences (descriptive)

90% season-aware moving-block bootstrap, blocks of four folds within a season, 5,000 resamples,
seed 0, `season_aware_moving_block_interval`. It decides nothing; the gates are read on point
estimates.

| Quantity | Candidate minus Control A: mean, 90% interval | Candidate minus Control B: mean, 90% interval |
| --- | --- | --- |
| below-q10 indicator | -0.0511 (seven folds of 137), [-0.0657, -0.0219] | -0.0146 (two folds), [-0.0365, 0.0000] |
| PIT | -0.0002, [-0.0034, 0.0021] | +0.0021, [0.0005, 0.0037] |

Tail flag, wins (left the tail), ties, losses (entered it): against Control A 7, 130, 0; the
seven are `2021-22-gw19`, `2022-23-gw18`, `2022-23-gw30`, `2022-23-gw37`, `2023-24-gw30`,
`2023-24-gw38`, `2024-25-gw37`. Against Control B 2, 135, 0; the two are `2021-22-gw19` and
`2023-24-gw30`. No fold enters the tail under the candidate that was outside it under either
control. Distance of the fold's PIT from 0.5, closer, same, farther: against Control A 94, 6,
37; against Control B 54, 7, 76. The PIT agrees exactly with Control A on 6 folds; the mean
absolute per-fold difference is 0.0177, the largest 0.07.

## What the joint draw changed

| Diagnostic (mean over 137 folds) | Candidate | Control A | Control B |
| --- | --- | --- | --- |
| within-club Pearson correlation of scenario points, same-club squad pairs (7.76 pairs per squad on average, every squad has one) | 0.1818 | 0.0033 | 0.1847 |
| within-club Pearson correlation of sampled appearances, same pairs | 0.0030 | -0.0007 | -0.0007 |
| scenario standard deviation, per-fold ratio to Control A | 1.0964 (min 0.92, max 1.41); 0.9960 of Control B's | 1 | 1.1012 |
| q10 of the squad score minus Control A's | -1.16 points (0.11 below Control B's) | 0 | -1.05 points |
| sampled appearance rate of the squad | 0.9264 | not recorded | not recorded |
| source rows' appearance rate | 0.4372 | not applicable | not applicable |
| re-draw cells (target appears, source row did not), rate over appeared cells | 7,410 per fold, 0.5332 | not applicable | not applicable |
| re-draw block fallback cells (no appeared row of the position in the block) | 103 per fold; fold fallback 0 | not applicable | not applicable |
| history folds per draw; club-week blocks per fold; rows and appeared rows per block | 77.0; 18.9; 33.8 and 14.4 | 77.0 | 77.0; 18.9; 14.4 |
| fixture-count fallback rate over scenario-club cells; position fallback; blank cells; mixed blocks | 0.0897; 0; 0; 0 | not applicable | 0.0897 (same blocks); not recorded here |

Two things in that table carry the reading.

First, the appearance co-movement the candidate was built for is almost absent in the measured
squads: 0.0030 against -0.0007. A selected squad is made of near-certain starters (sampled
appearance rate 0.926), and a near-certain starter inherits little from a source row: with
`p_t` above `p_s`, the latent uniform of an appeared row is always below `p_t`, and that of a
rested row is below `p_t` most of the time (the re-draw rate of 0.53 says so). Where the
inheritance does bite is the rare rested week of a regular, and that is a tail event by
construction, which is where the two folds against Control B sit: on `2021-22-gw19` the
realized 39 falls below Control B's q10 of 39.04 and not below the candidate's 38.97; on
`2023-24-gw30` the realized 46 falls below Control B's 46.58 and not below the candidate's
45.95. The candidate's q10 is 0.11 points lower than Control B's on average, from an
appearance atom that occasionally fires together.

Second, the rest of the candidate is the block sampler: the same blocks, the same position rule,
and a residual that is either the source row's own or a uniform re-draw among the block's
appeared rows of the position, which is Control B's draw. The within-club points correlation
(0.18 against 0.18), the standard deviation (0.996 of Control B's) and the mean PIT (0.0021
higher) say the same. The candidate's pass and Control B's fail are two folds apart on a band
whose edge sits between 21 and 22; the interval of the difference against Control B touches
zero. The reading is that the zero atom drawn inside the block buys about two folds of lower
tail beyond the block, on this population, and that this is enough to land inside the band and
not more.

## Verdict against the pin condition

- Declared gate: G1 and G2 hold, `candidate_within_gates`.
- Decision-level reading on the 147 folds: not applicable, the sampler does not feed expected
  points; recorded as such in the record.
- S1 and S2 not worse than the control: G3 holds against Control A (the foundation, the
  current component sampler). Against Control B, which is itself unmerged and outside S2, the
  tail count is not greater and the mean PIT is 0.002 farther from the centre.

The candidate therefore meets the pin condition as written. The record also says what the margin
is: one fold on S2, a pass that a different seed or a regenerated table could move, as #1145's
one-fold fail showed in the other direction. The owner's call, with that stated.

## What this record is and is not

- A development measurement on the frozen Phase D population and gates, on the frozen binding
  table, with a verified fidelity precondition. It is not the binding verdict and does not
  touch the binding record.
- `locked_holdout_accessed: false`. 2025-26 is excluded by the population and refused by the v1
  export.
- The noise floor is stated as the repository requires: an effect smaller than 1.5 points per
  gameweek is not certified. This record makes no points claim; its gates are the S1 and S2
  bands.
- Not measured: the V1 sampler `generate_scenarios` (no minutes, no appearance state, so the
  official autosub scorer cannot read it; stated in the protocol), opponent pairing, the
  captain's second copy, dispersion scales, location shifts, multi-week paths, any decision-level
  reading. A next step needs its own pre-registration.
