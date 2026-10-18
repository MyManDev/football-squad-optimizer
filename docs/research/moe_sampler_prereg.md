# Joint team-match sampler (zero atom and club block in one draw): pre-registration

Status: frozen on 2026-10-17 before the sampler code, before the runner changes and before any
measurement. Nothing in this protocol changes after a number is seen. Measurement only, nothing
promoted: `PHASE_E_CALIBRATED_VERSIONS` stays empty whatever the verdict, no product default
changes, and a pin is a separate reviewed change by the owner after reading the records.

The records that fulfil this protocol are `docs/research/moe_sampler_fidelity.json` with its
Markdown twin and `docs/research/moe_sampler.json` with its twin. Both are written by this
protocol's runners after it is committed; neither exists while this document is being frozen.

Line 2 (`sampler`) of the mixture-of-experts programme. The branch is `feat/moe-sampler`, based
on `origin/feat/team-match-block-sampler` (PR #1145: `develop` plus the block sampler, its
runner flags and its records). The block sampler is re-used as committed there, not
re-implemented and not changed; this protocol adds a further declared option beside it.

## Question

The repository has two component samplers and one measured candidate:

- The foundation sampler (`sample_component_scenarios` with no candidate keyword,
  `component_scenario_foundation_v1`, `residual_selection: fold_uniform`). This is the V2
  component sampler of the repository's own naming (`docs/rank_tail_selector_prereg.md`: "the
  V2 component sampler"): it carries the zero atom (a per-player appearance Bernoulli) and no
  team co-movement. In this protocol "the foundation" and "V2" name this one object.
- The V1 sampler (`generate_scenarios` in `scenarios/generator.py`): team co-movement through
  the point decomposition, no zero atom and no minutes. It is not measured here, see below.
- The #1145 candidate `team_match_block_v1`: the foundation's appearance draw, then one source
  club-week block per target club inside the scenario's source fold for the paired residual.
  It passed S1 and failed S2 by one fold (22 of 137, 0.1606) against the foundation's 25.

In `team_match_block_v1` the appearance Bernoulli is still drawn per player, independently of
the block: a club that rotated six starters in the source week lifts no co-movement into the
target squad's appearances. The candidate measured here draws the appearance from the block
too, so the zero atom and the club co-movement come from one draw, and the conditional
residual is drawn within the same block.

The question is one reading of the two frozen gates: does the candidate, read on the frozen
population, decisions, scenario count and seed, lie inside S1 and S2, and does it not read
worse than the foundation on either?

## The table

On this machine the frozen binding Phase C v1 export exists with the digests the binding record
pins (table `b05f10c3...`, roster `3ef0c571...`, manifest `1a06b69a...`); the three files were
copied unchanged to the run directory and verified by digest. Every arm is read on that table.
This differs from #1145, which had to regenerate the table on Linux and read both its arms on a
table with a different digest. Consequence: the foundation control arm here is expected to
reproduce the frozen binding record (S1 0.5147, S2 28 of 137) wherever the frozen decisions
reproduce; where it does not, the record says so, and the arms drawn in one run on one table
remain the comparison.

## Population and gates

Identical to `docs/phase_d_component_squad_calibration_prereg.md`, which the runner enforces:

- The 147 Phase C v1 OOF decisions, each optimized over the complete player pool before
  scenario eligibility is inspected, under the measurement optimization profile.
- Nine history burn-in folds (`2021-22-gw02` to `2021-22-gw10`) and the single direct-control
  abstention (`2021-22-gw15`) excluded; the population is the frozen 137 folds from
  `2021-22-gw11` to `2024-25-gw38`. A different population stops the run without a verdict.
- The realized official score of the same frozen decision (`OFFICIAL_AUTOSUB_CAPTAIN_V2`).
- `ScenarioConfig()` defaults: `scenario_count=1000`, `deterministic_seed=0`,
  `min_history_folds=8`, `double_gameweek_scale=1.0`. No shift, no scale, no recentering.
- Per fold `t`: `PIT_t = count(S_t <= R_t) / 1000`, `q10_t` the linear tenth percentile,
  `L_t = 1[R_t < q10_t]`. S1: the mean of `PIT_t` over the 137 folds lies in [0.43, 0.57],
  inclusive. S2: the mean of `L_t` lies in [0.04, 0.16], inclusive. Point estimates decide.
- 2025-26 is not read: the frozen population excludes it and the v1 export refuses it.

## The candidate sampler `team_match_joint_v1`

A frozen dataclass `TeamMatchJointConfig` with the contract version `team_match_joint_v1` and
no tunable number, passed as `team_match_joint=` to `sample_component_scenarios`, mutually
exclusive with `conditional_residuals=` and `team_match_block=`. Left absent, the foundation
sampler and the block sampler are byte-identical, which a fingerprint test proves.

### The pool

`team_match_joint_pool` builds a `TeamMatchJointPool` from the Phase C rows strictly before
the target. Unlike `paired_conditional_residuals`, it keeps the non-appearance rows, since an
appearance drawn from a block needs to see who did not play:

- `component_model` rows only; `direct_control` rows produce nothing.
- `appearance_target` must be 0 or 1 and `appearance_probability` finite in [0, 1]; a row
  failing either is excluded and counted, never filled.
- `team_id`, `position` and `fixture_count` must be present on every row (the v1 table takes
  `team_id` and `position` from the decision roster; the runners supply the join as #1145's
  do). A row with `fixture_count` 0 has no match to appear in and is excluded and counted (on
  the frozen table there is none).
- An appeared row (`appearance_target == 1`) carries its paired residuals against the row's
  own conditional means; a row with a non-finite target is excluded and counted (none on the
  frozen table). A non-appeared row carries no residual (missing, never zero), and the draw
  never reads one as a residual, which the code checks on every draw.
- The history folds are those with at least one appeared row, in sorted `fold_id` order, the
  same set `paired_conditional_residuals` yields; `min_history_folds` applies as there.
- Canonical order: `fold_id`, then `player_id`.

### The draw, per scenario, in generator order

1. `v ~ U(0, 1)` per cell, one `random((scenarios, players))` call: the foundation's own first
   call in the same shape.
2. Source fold: one `integers(0, folds)` per scenario, the foundation's own second call. A draw
   with and without this config therefore shares its source folds seed for seed.
3. Club-week blocks: within the chosen fold the pool's rows (appeared and not) are grouped by
   source `team_id`. A block's fixture count is the rows' common value (most frequent, larger
   on a tie, counted as mixed when they differ). For every target club (distinct `team_id` of
   the roster in order of first appearance, fixture count the players' largest), one block is
   drawn uniformly among the fold's blocks with that fixture count, or among all its blocks
   when none has it (counted as a fixture-count fallback). One `integers(0, high)` call over a
   (scenarios, clubs) array. A target club with fixture count 0 has blank cells (counted) and
   its players never appear, by the ceiling rule the foundation already has.
4. Source row: every player draws one row uniformly among the chosen block's rows of the same
   position, or among all the block's rows when it has none (counted as a position fallback).
   One `integers(0, high)` call over a (scenarios, players) array.
5. Appearance: with the source row's observed appearance `a_s` and its predicted probability
   `p_s`, the row's latent uniform is `u = v * p_s` when `a_s = 1` and `u = p_s + v * (1 - p_s)`
   when `a_s = 0`. The target player appears iff `u < p_t`, with `p_t` the target's own
   `appearance_probability` from the component table, and the ceiling is positive. Marginally
   `P(appear) = p_t` exactly when the source rows' appearance model is calibrated on the block's
   rows; a miscalibration of the source rows passes through to the sampled level, and the
   fidelity reading's appearance difference measures how much.
6. Conditional residual: a target that appears from a source row that appeared takes that row's
   paired (minutes, points) residual. A target that appears from a source row that did not
   appear draws one row uniformly among the block's appeared rows of the same position, else
   among the block's appeared rows, else among the fold's appeared rows (each level counted;
   the re-draw cells are counted and their rate over appeared cells reported). One
   `random((scenarios, players))` call, scaled by the applicable count, consumed after the row
   draw. Non-appearances read no residual.
7. Unchanged from the foundation: the one-minute floor, the `90 * fixture_count` ceiling, the
   non-clipping of points, the zeroing of non-appearances, the seed derivation (`_draw_seed`)
   and the scenario identity fields.

Diagnostics recorded on every draw: `residual_selection: "team_match_joint"`, the contract
version, history folds, blocks per fold, rows and appeared rows per block, target clubs, the
fixture-count fallback count and rate, blank-club cells, the position fallback count and rate,
mixed-fixture blocks and target clubs, the source rows' appearance rate, the sampled appearance
rate, the re-draw cells and rate, and the re-draw fallback counts by level.

## Arms

All drawn in one run, on every measured fold, on the same table, frozen decision, scenario
count, seed and scorer:

- Candidate: `team_match_joint_v1`.
- Control A, the foundation (V2, zero atom, no co-movement): `fold_uniform`, drawn on a
  `paired_conditional_residuals` pool built with the block fields.
- Control B, the #1145 block sampler: `team_match_block_v1`, drawn on the same pool as A with
  `team_match_block=TeamMatchBlockConfig()`, its code unchanged.
- Quoted, not drawn: the frozen binding record (foundation, frozen table), and the #1145
  records (regenerated table).

Not drawn: the V1 sampler `generate_scenarios`. It publishes no minutes and no appearance
state, so the official autosub and captain scorer that defines S1 and S2 cannot score it, and
scoring it under a different rule would compare two scorers rather than two samplers. It is
recorded as not measured, with this reason.

## Readings

Per arm, over the 137 folds: S1 mean PIT; S2 lower-tail count and rate; upper-tail count and
rate (PIT at or above 0.95); PIT at or below 0.05; mean q10; mean scenario standard deviation;
per-season readings (descriptive). Paired per-fold differences, candidate minus Control A and
candidate minus Control B, of `L_t` and of `PIT_t`: mean and a 90% season-aware moving-block
bootstrap interval (`season_aware_moving_block_interval`, `PromotionPolicy(confidence_level=
0.90, bootstrap_resamples=5000, moving_block_length=4, deterministic_seed=0)`), wins, ties and
losses on the tail flag, and the folds whose tail flag differs from each control, listed. Within-
club Pearson correlation of scenario points and of sampled appearances over the squad's same-
club pairs, all three arms. The block diagnostics pooled as means. The intervals are
descriptive: the gates are read on point estimates, as the binding protocol says.

## Gate

Read once, on the candidate arm's 137 folds:

- G1: S1 mean PIT in [0.43, 0.57].
- G2: S2 lower-tail rate in [0.04, 0.16].
- G3 (the pin condition's "not worse than the control", against Control A): the candidate's
  `|mean PIT - 0.5|` is not greater than Control A's, and its lower-tail count is not greater
  than Control A's. Point estimates, tolerance 1e-9.
- G4, reported beside G3 and deciding nothing: the same two comparisons against Control B.

Verdict: `candidate_within_gates` when G1 and G2 hold, `candidate_outside_gates` otherwise,
`abstained` on any population mismatch, a missing or structurally invalid fidelity record or
fewer than 137 folds. Proposed for a pin only when G1, G2 and G3 all hold. The verdict is not
softened and the run is not repeated.

No decision-level reading: the sampler does not feed expected points, so the 147-fold decision
reading of the pin condition does not apply; the record says so.

## Fidelity precondition

`scripts.measure_component_fidelity --team-match-joint`, pinned to the three frozen digests,
under `ScenarioConfig()` defaults, run first and committed as `docs/research/moe_sampler_fidelity.json`
under the contract `phase_d_component_fidelity_candidate_v1`. It registers no threshold. The
calibration run verifies it structurally (contract, digests, sampler, configuration, population)
and abstains without it. Its differences are reported beside the frozen foundation record and
the #1145 candidate record and cannot be used to tune or rescue S1 or S2.

## Runner contract

Both runners gain `--team-match-joint`. On the v1 contract the run is pinned to the three
expected digests, cannot write the binding record's path, is refused beside any other candidate
flag, carries `binding: false`, and names the sampler's contract version in `sampler`,
`candidate` and every fold record. The calibration run with this flag draws Controls A and B
beside the candidate and records them under `control_arm` and `block_arm`. The binding path and
the `--team-match-block` path are unchanged byte for byte.

Seed and draw count, restated: `deterministic_seed=0`, `scenario_count=1000`, per fold, every
arm; the seed stream is derived by `_draw_seed` from the target, the table and roster digests.

## Not measured

The V1 sampler (reason above), opponent pairing, the captain's second copy, dispersion scales,
location shifts, multi-week paths, any decision-level reading, 2025-26.

## Commits

1. This protocol.
2. The sampler, the pool, the runner flags and the tests, before any measurement.
3. The fidelity record and its twin.
4. The calibration record, its twin, the index rows, the catalogue rows and the README link.
