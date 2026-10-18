# Joint team-match sampler on the S1 and S2 calibration gates

**Protocol verdict at the frozen seed 0: `candidate_within_gates`.** Measured, not certified,
and not robust by a seed reading added after the result (2026-10-18, at `d3b9dab1`). The candidate sampler `team_match_joint_v1` passes S1 (mean PIT 0.5207 in
[0.43, 0.57]) and, at seed 0, passes S2: the realized squad score fell below its own scenario
tenth percentile in 21 of 137 folds, a rate of 0.1533 against the band [0.04, 0.16]. The margin
is one fold: 22 would be 0.1606 and outside. The foundation sampler, read as Control A on the
same frozen table, decisions, scenarios and seed, gives 28 of 137 (0.2044), reproducing the
frozen binding record's count; the #1145 block sampler as Control B gives 23 of 137 (0.1679).
G1, G2 and G3 of the pre-registration hold at seed 0; G4 (descriptive) does not, by the mean
PIT clause alone. That verdict is recorded as it fell and is not re-run.

Added after the result, on 2026-10-18 (descriptive, decides nothing; see
[the seed reading](#seed-sensitivity-added-after-the-result)): the pass is not robust.
Re-drawing the twelve folds whose PIT lies near 0.10 under seeds 0 to 9 gives the candidate S2
counts of 21 to 25, mean 23.4, inside the band on 1 of 10 seeds (seed 0); the block sampler 23
to 26, mean 24.0, inside on none. The candidate's expected count lies above the band. Its lower
q10 against the block sampler is mostly a location shift of about -0.16 points, not a fatter
lower tail. These 137 folds had been read by three samplers before this one, and the sampler
was declared after the block sampler's record listed its boundary folds, so this is development
evidence on reused folds. It is not a basis for a pin: the repository's pin rule
needs the binding Phase D artifact, and a candidate sampler needs a reading on folds no sampler
was chosen on (prospective 2026-27 gameweeks) under a reviewed amendment of the Phase E
pre-registration. Nothing is promoted: `PHASE_E_CALIBRATED_VERSIONS` stays empty, no
probability is published, no product default changes.

Protocol: [moe_sampler_prereg.md](moe_sampler_prereg.md), frozen before the code (commit
`122350cf`); nothing in it changed after. Record: [moe_sampler.json](moe_sampler.json), contract
`phase_d_component_squad_calibration_candidate_v1`, `binding: false`. Written by
`python -m scripts.run_component_squad_calibration --team-match-joint`, launched at commit
`daa908df` on a clean tree at 16:50:05Z (the sampler is commits `0a4f88ee` and `650e6371`;
`daa908df` adds the fidelity record). The record's `provenance.repository_commit` names
`7283993e`, which was committed at 16:52:19Z while the run was going: the runner stamps its
provenance again after measuring, and `7283993e` changes only documents (the fidelity twin and
its index row), so the code that ran is `daa908df`'s. 2026-10-17 16:50Z to 17:28Z, 2,311
seconds on the owner's Windows 11 machine (32 logical CPUs, shared with three other measurement
runs), Python 3.13.5, numpy 2.5.2, pandas 3.0.5, OR-Tools 9.15.6755, archive commit `8c97b2ad`.
Solver: 106 of 147 decisions OPTIMAL, 41 FEASIBLE under the deterministic 5.0 budget. Fidelity
precondition: [the candidate fidelity record](moe_sampler_fidelity.md), verified structurally
before the read (digest `479bddad...`). 2025-26 not read.

## The table

Every arm was read on the frozen binding Phase C v1 table itself (table `b05f10c3...`, roster
`3ef0c571...`, manifest `1a06b69a...`), not on a regenerated one as #1145 had to. Against the
frozen binding record, Control A reproduces the realized score and the PIT of 127 of 137
decisions exactly and the tail flag of all 137. By scenario and component fingerprint, 11
decisions differ from the frozen run, all FEASIBLE in both runs: ten move their realized score
(`2021-22-gw11`, `2021-22-gw14`, `2022-23-gw06`, `2022-23-gw09`, `2022-23-gw15`, `2023-24-gw15`,
`2024-25-gw18`, `2024-25-gw20`, `2024-25-gw23`, `2024-25-gw30`), and `2024-25-gw08` keeps its
realized score and PIT with a different decision (q10 46.19 against 45.74). Seven of the ten are
among the ten #1145 reported; #1145's other three (`2023-24-gw12`, `2023-24-gw17`,
`2024-25-gw14`) reproduce here. The frozen run (2026-09-07, commit `972f55f9`) solved under the
default `OptimizationConfig()`, a ten-second wall-clock budget, and this run under the
deterministic 5.0 budget, so a solve that stops FEASIBLE can stop at a different incumbent. The
decisions are re-solved in every run, which is a second source of run-to-run movement in S2
beside the seed. That is why Control A's mean PIT is 0.5209 against the record's 0.5147 while
its tail count is the record's 28.

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

The season pattern is the one every sampler shows. 2023-24 fails S2 under all three (0.2973
under the candidate). 2022-23 sits below the S2 band under both block samplers (1 of 36, 0.0278)
with a mean PIT above the S1 band. Under the candidate the pooled count combines two seasons
above the band (2021-22 at 0.2222, 2023-24 at 0.2973), one below it (2022-23 at 0.0278) and one
inside it (2024-25 at 0.0811). The pooled reading decides; the seasons cannot overturn it.

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
| history folds per draw; club-week blocks per fold; rows and appeared rows per block | 77.0; 18.9; 33.8 and 14.4 | not recorded (note 1) | not recorded (note 2) |
| fixture-count fallback rate over scenario-club cells; position fallback; blank cells; mixed blocks | 0.0897; 0; 0; 0 | not applicable | not recorded (note 2) |

Note 1: Control A draws on the paired pool built from the same history rows, and the record's
pool exclusions are zero apart from direct-control rows, so its history folds are the
candidate's by the protocol's pool rule; this record does not carry them.

Note 2: this record carries the block diagnostics of the candidate only. #1145's record
(`team_match_block_sampler.json`, measured on its regenerated table with other decisions) reads
77.0 history folds, 18.9 blocks per fold, 14.4 appeared rows per block and a fixture-count
fallback rate of 0.0897 for the block sampler; those are quoted from there, not measured here.

Two things in that table carry the reading.

First, the appearance co-movement the candidate was built for is almost absent in the measured
squads: 0.0030 against -0.0007. A selected squad is made of near-certain starters (sampled
appearance rate 0.926), and a near-certain starter inherits little from a source row: with
`p_t` above `p_s`, the latent uniform of an appeared row is always below `p_t`, and that of a
rested row is below `p_t` most of the time (the re-draw rate of 0.53 says so). The two folds
that leave the tail against Control B at seed 0 are `2021-22-gw19` (the realized 39 falls below
Control B's q10 of 39.04 and not below the candidate's 38.97) and `2023-24-gw30` (46 below
Control B's 46.58, not below the candidate's 45.95). Added after the result on 2026-10-18
(descriptive): both sit within 0.06 points of the candidate's q10 at a PIT of 0.101, inside one
Monte Carlo standard error of 0.10, and the seed reading below (run at `d3b9dab1`) flags each of
them under the candidate on 7 seeds of 10 (Control B: 9 and 8). Whether the inherited
appearance changes the tail on a regular's rested week is a hypothesis this record does not
test.

Second, the rest of the candidate is the block sampler: the same blocks, the same position rule,
and a residual that is either the source row's own or a uniform re-draw among the block's
appeared rows of the position, which is Control B's draw. The within-club points correlation
(0.18 against 0.18) and the standard deviation (0.996 of Control B's) say the same.

Added after the result on 2026-10-18 (descriptive, decides nothing), computed from the record's
fold entries by `scripts.redraw_component_calibration_seeds` at commit `d3b9dab1` and recorded
under `seed_sensitivity_added_after_the_result.location_against_block_arm`: what differs is
location. Fold by fold, the candidate's scenario mean sits 0.156 points below Control B's on
average (lower on 92 of 137 folds), its q10 0.110 lower and its standard deviation 0.055
smaller. Measured from each arm's own mean, the candidate's q10 is 0.045 higher than Control
B's, so its lower tail is thinner relative to its centre, and it is deeper than Control B's on
only 62 folds. Moving Control B's q10 by the candidate's per-fold mean difference and nothing
else takes Control B from 23 to 22 below q10 (`2021-22-gw19` leaves). The mean PIT difference
of +0.0021 [0.0005, 0.0037], recorded at the result, is the same downward shift, and it is why
G4 fails on the PIT clause. The shift is consistent with the uniform appearance shortfall the
fidelity record shows (-0.0039 sampled minus predicted, below zero in every fold); that link is
not tested here. So the seed-0 edge over Control B comes mostly from a location shift that also
moves S1 farther from the centre, not from the shape of the lower tail.

## Seed sensitivity (added after the result)

Descriptive, decides nothing. Added on 2026-10-18 after review, run at commit `d3b9dab1` on a
clean tree by `python -m scripts.redraw_component_calibration_seeds` on the frozen inputs (the
three digests verified against the binding pins), 2026-10-18 13:37Z to 14:34Z, on the same
machine and archive. Recorded in [moe_sampler.json](moe_sampler.json) under
`seed_sensitivity_added_after_the_result`; every key recorded before is unchanged.

The twelve folds whose PIT lies in [0.06, 0.14] under either arm (`2021-22-gw19`,
`2021-22-gw20`, `2022-23-gw18`, `2022-23-gw30`, `2022-23-gw37`, `2023-24-gw05`, `2023-24-gw19`,
`2023-24-gw30`, `2023-24-gw38`, `2024-25-gw06`, `2024-25-gw27`, `2024-25-gw37`) were re-solved
under the measurement profile, as the calibration run solves them, and both arms were re-drawn
on the calibration run's own pools under seeds 0 to 9. Seed 0 reproduced the record's readout
of both arms on every one of them. The other 125 folds keep their recorded flags (19 under the
candidate, 19 under Control B): their PITs sit at least 0.041 from 0.10, 4.3 Monte Carlo
standard errors at 1,000 scenarios (0.0095).

| S2 count by seed | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | mean | seeds inside [0.04, 0.16] |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Candidate | 21 | 22 | 23 | 25 | 25 | 23 | 25 | 24 | 23 | 23 | 23.4 | 1 of 10 |
| Control B | 23 | 24 | 24 | 24 | 23 | 26 | 26 | 23 | 23 | 24 | 24.0 | 0 of 10 |

Flagged seeds of 10 on the re-drawn folds, candidate / Control B: `2021-22-gw19` 7 / 9;
`2021-22-gw20` 10 / 10; `2022-23-gw18` 0 / 0; `2022-23-gw30` 4 / 4; `2022-23-gw37` 0 / 0;
`2023-24-gw05` 0 / 0; `2023-24-gw19` 10 / 10; `2023-24-gw30` 7 / 8; `2023-24-gw38` 0 / 1;
`2024-25-gw06` 0 / 0; `2024-25-gw27` 4 / 5; `2024-25-gw37` 2 / 3.

A plug-in reading from the record's own PITs, taking each fold's PIT as the true probability that
a scenario scores at or below the realized score and bracketing the flag by at most 99 or at
most 100 such scenarios of 1,000: the candidate's expected count is 22.7 to 22.9, with a
probability of 21 or fewer of 0.08 to 0.11; Control B's is 23.1 to 23.2 (0.010 to 0.016).
The recorded PIT is itself one draw, so this is a rough reading beside the re-draws, not an
estimate with a stated error.

Both readings put the candidate's expected count above the band's ceiling of 21, and the seed-0
count of 21 at the low end of its spread. Across seeds the candidate's count is below Control
B's by 0.6 folds on average, not two. The candidate's S2 pass is a draw at the edge of the band,
not a property of the sampler that a second seed reproduces.

## Development evidence on reused folds

These 137 folds are not fresh for this sampler. Before it, the S2 gate had been read on them
for the foundation sampler (the binding run, 28 of 137), for the conditional residual sampler
`component_scenario_conditional_residual_v1`, which passed S1 and S2 in a development
measurement that [the conditional development method](../phase_e_conditional_development_method.md)
records as not independent validation (its numbers are not committed), and for
`team_match_block_v1` (#1145: 22 of 137 on the regenerated table, 23 here). The protocol's
Question lists two component samplers and one measured candidate and leaves out the conditional
residual sampler's pass.

The joint pre-registration (`122350cf`, committed 2026-10-17 16:29:48Z) was written after
#1145 committed its record (12:45Z), which lists the five folds whose tail flag the block
sampler changed (`2021-22-gw19`, `2022-23-gw37`, `2023-24-gw38`, `2024-25-gw27`,
`2024-25-gw37`). All five are among the boundary folds of the seed reading above, and
`2021-22-gw19` is one of the two folds of this record's edge over Control B. A script saved at
16:27:23Z, two minutes before that commit, in the run's working directory and not committed,
reads the frozen table over every fold: the club-week block structure, and the realized
appearance rate against the predicted probability in ten bins of width 0.1. The fidelity twin
quotes its output. The sampler was declared with #1145's fold-level results in view and, by
that timing, with a reading of this table's appearance calibration; its reading on these folds
is development evidence, not validation.

## What a pin would need

This section was rewritten on 2026-10-18. The earlier text (commit `b9dce61b`) said the
candidate met "the pin condition as written"; that conflicted with the repository's pin rule
below and is withdrawn.

- Declared gate, at seed 0: G1 and G2 hold, `candidate_within_gates`; G3 (not worse than the
  foundation) holds; G4 against Control B, descriptive, fails on the mean PIT clause. The
  decision-level clause is not applicable: the sampler does not feed expected points.
- "The pin condition" in the protocol and in the record is that protocol's name for a condition
  made of its G3 clause ("not worse than the control") and a 147-fold decision reading; the
  record's `decision_level_reading` uses the term for the decision clause and marks it not
  applicable. No document in the repository defines it.
- The repository's pin rule is in
  [the Phase E pre-registration](../phase_e_candidate_selection_prereg.md#calibration-pin):
  `PHASE_E_CALIBRATED_VERSIONS` stays empty until the binding Phase D artifact records
  `calibrated_internal`, and the pin matches `(phase_c_control_components_v1,
  component_scenario_foundation_v1)`; `src/squadopt/application/phase_e.py` says to populate it
  only in a reviewed change citing that binding artifact. The binding artifact,
  `docs/phase_d_component_squad_calibration.json`, records `failed`. This record is
  `phase_d_component_squad_calibration_candidate_v1` with `binding: false`. The rule is not met.
- For a candidate sampler the repository has a precedent: the conditional development method
  says the conditional residual sampler's pass on these folds authorizes no pin, and that the
  prospective live-readiness gate and a reviewed amendment naming the sampler remain necessary.
- A pin of `team_match_joint_v1` therefore needs a reading on folds no sampler was chosen on,
  that is prospective 2026-27 gameweeks settled after this record, under a reviewed amendment of
  the Phase E pre-registration that names the sampler and declares the reading before it is
  made. With a margin of one fold inside the Monte Carlo spread, that reading should not rest on
  a single seed.

## What this record is and is not

- A development measurement on the frozen Phase D population and gates, on the frozen binding
  table, with a verified fidelity precondition, on folds earlier samplers were read on. It is
  not the binding verdict and does not touch the binding record.
- `locked_holdout_accessed: false`. 2025-26 is excluded by the population and refused by the v1
  export.
- The noise floor is stated as the repository requires: an effect smaller than 1.5 points per
  gameweek is not certified. This record makes no points claim; its gates are the S1 and S2
  bands.
- Not measured: the V1 sampler `generate_scenarios` (no minutes, no appearance state, so the
  official autosub scorer cannot read it; stated in the protocol), opponent pairing, the
  captain's second copy, dispersion scales, location shifts, multi-week paths, any decision-level
  reading. A next step needs its own pre-registration.
