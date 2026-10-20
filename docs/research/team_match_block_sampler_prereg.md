# Team-match block resampler for component scenarios: pre-registration

Status: frozen on 2026-10-17 before the sampler code, before the runner changes and before any
measurement. Nothing in this protocol changes after a number is seen. Measurement only, nothing
promoted: `PHASE_E_CALIBRATED_VERSIONS` stays empty whatever the verdict, and a promotion needs
its own pre-registration and a member-facing decision by the owner.

The records that fulfil this protocol are `docs/research/team_match_block_sampler.json` with its
Markdown twin, and `docs/research/team_match_block_sampler_fidelity.json` with its twin. Both are
written by this protocol's runners after it is committed; neither exists while this document is
being frozen, and their rows in the measurements index link them.

## Question

The Phase D component sampler (`sample_component_scenarios` in
`src/squadopt/scenarios/components.py`) draws one source fold per scenario and then, for every
player, one paired (minutes, points) residual row uniformly from that fold. The binding squad
calibration (`docs/phase_d_component_squad_calibration.json`, 137 folds, 1,000 scenarios, seed 0)
passed S1 (mean PIT 0.5147 in [0.43, 0.57]) and failed S2: the realized squad score fell below
its own scenario tenth percentile in 28 of 137 folds (0.2044 against [0.04, 0.16]). The lower tail
is roughly twice too thin.

`phase2_tail_diagnostic` found that one global dispersion scale repairs one season and breaks
another. `phase2_captain_attribution` found that the captain's second copy carries part of the
failure but not the failure. The common gameweek shock co-moves weakly with the squad gap. The
remaining hypothesis is structural: the independent per-player row draw destroys the within-club
co-movement of residuals (a club that scores four lifts every attacker, a clean sheet lifts every
defender), and an optimizer-selected squad concentrates players whose errors co-move. The
candidate measured here keeps the fold block and adds a club block inside it.

The question is one reading of the two frozen gates: does the candidate sampler, read on the same
population, decisions, scenario count and seed as the binding record, lie inside S1 and S2?

## Step 1: the Phase C v1 table was regenerated and its digest differs

On a clean tree at the branch start (commit `1079ba64`, the head of `develop`),
`python -m scripts.export_component_oof --output-dir artifacts/phase_c` wrote:

| Artifact | Regenerated digest | Digest the binding record pins |
| --- | --- | --- |
| table | `6dd22797c9ec1cb6328e906dd0b19964535b4d0f4fe1f736eed27607a682b82a` | `b05f10c3fd3ab5058fe1ff720cc6ef0a4b1362a70a19dd979ad0eb0f47d12c01` |
| roster | `3ef0c5717fa63c3c4772512f019cd750d3fae6cd9a7567d20dd4bfa24003678e` | `3ef0c5717fa63c3c4772512f019cd750d3fae6cd9a7567d20dd4bfa24003678e` |
| manifest | `66096a7cb5eea05a4bf2892f971b8468489cbe5d1a9bb509dcb88430a3fd17b4` | `1a06b69abb3d7fe98afde6983885a9a7723463d351a2432dc9e0a11082f5eba8` |

The roster is byte-identical. The table differs in bytes but not in structure: 101,447 rows,
100,130 `component_model` rows, 1,317 `direct_control` rows, 147 folds, and on every one of the
138 folds the frozen fidelity record measured, the regenerated table gives the same number of
component rows and the same residual pool size as that record. The binding record's export ran at
commit `a43c0ec5` on the owner's Windows machine; this one ran at `1079ba64` on Linux. The
difference is therefore in the fitted prediction values, not in which rows exist. The manifest
differs because it carries the table digest and the producing commit.

Consequence, fixed here: the frozen binding record is not the control arm. Both arms, the
foundation sampler and the candidate, are read on the regenerated table in one run, on the same
frozen decisions, so the comparison is on one table. The frozen record's S1 and S2 are quoted
beside them as the published reading, not as the control. If the foundation arm on the
regenerated table does not reproduce the frozen verdict (S1 pass, S2 fail), the record says so and
the candidate's reading is still reported; it is then a reading on a table that differs from the
binding one, and the record says that too.

## Population and gates

Identical to `docs/phase_d_component_squad_calibration_prereg.md`, restated so the runner can
refuse any departure:

- The 147 Phase C v1 OOF decisions, each optimized over the complete player pool before scenario
  eligibility is inspected, under the measurement optimization profile the binding run used.
- Nine history burn-in folds (`2021-22-gw02` to `2021-22-gw10`) and the single direct-control
  abstention (`2021-22-gw15`) are excluded; the population is the frozen 137 folds from
  `2021-22-gw11` to `2024-25-gw38`. A runner that observes a different population, first fold,
  last fold or direct-control abstention stops without a verdict.
- The realized official score of the same frozen decision, scored by the official autosub and
  captain rules (`OFFICIAL_AUTOSUB_CAPTAIN_V2`).
- `ScenarioConfig()` defaults: `scenario_count=1000`, `deterministic_seed=0`,
  `min_history_folds=8`, `double_gameweek_scale=1.0`. No location shift, no dispersion scale, no
  recentering, no reweighting.
- Per fold `t`: `PIT_t = count(S_t <= R_t) / 1000`, `q10_t` the linear tenth percentile,
  `L_t = 1[R_t < q10_t]`. S1: the mean of `PIT_t` over the 137 folds lies in [0.43, 0.57],
  inclusive. S2: the mean of `L_t` lies in [0.04, 0.16], inclusive. Point estimates decide.
  Per-season readings are descriptive and cannot overturn the pooled reading.
- 2025-26 is not read. The frozen population excludes it, the v1 export refuses it, and this task
  adds nothing there (`locked_holdout_accessed: false`).

## The candidate sampler `team_match_block_v1`

A frozen dataclass `TeamMatchBlockConfig` with the contract version `team_match_block_v1` and no
tunable number. Passed as `team_match_block=` to `sample_component_scenarios`, mutually exclusive
with `conditional_residuals=` (both given is refused). Left absent, the foundation sampler is
byte-identical, which a fingerprint test proves on the existing synthetic fixtures.

The residual pool is built by `paired_conditional_residuals` with the same row filter and the
same canonical order as today. For this candidate the pool additionally carries, per row, the
source row's `team_id`, `position` and `fixture_count`; a frame missing any of the three is
refused rather than filled. In both binding runners the source `team_id` comes from the Phase C
decision roster, joined on the handoff key, since the v1 OOF table does not carry it.

For every scenario, in this order:

1. **Appearance and source fold.** The appearance matrix and the source fold are drawn exactly as
   the foundation sampler draws them, from the same generator stream in the same order. A draw
   with and without this config shares its appearances and its source folds seed for seed.
2. **Club-week blocks.** Within the chosen fold, the pool's rows are grouped by source `team_id`.
   Each group is one club-week block. A block's fixture count is the common `fixture_count` of
   its rows; if the rows ever disagree, the most frequent value, the larger on a tie, and the
   block is counted as a mixed-fixture block. (On the regenerated table no club-week block and no
   target club-week is mixed: 2,804 blocks over 147 folds, 14.8 rows per block on average.)
3. **One block per target club.** The target clubs are the distinct `team_id` values of the
   target roster, in order of first appearance in the roster's player order. A target club's
   fixture count is the common `fixture_count` of its players (if they disagree, the largest, and
   the club is counted). For every target club, one block is drawn uniformly among the chosen
   fold's blocks whose fixture count equals the target club's. When no such block exists, one is
   drawn uniformly among all the fold's blocks, and the scenario-club cell is counted as a
   fixture-count fallback. Clubs are drawn independently, with replacement across target clubs:
   two target clubs may draw the same source block. A target club with no fixture in the target
   week has no matching block by construction (every pool row is an observed appearance, so no
   block has fixture count zero); its players are non-appearances already, its cells are counted
   as blank-club cells and excluded from the fixture-count fallback count. The block draw is one
   `generator.integers(0, high)` call over a (scenarios, clubs) array of option counts, consumed
   after the fold choice and before the row choice.
4. **One row per player.** Every player of the target club draws one row uniformly among the
   chosen block's rows of the same position. When the block has no row of that position, the
   player draws uniformly among all the block's rows, and the scenario-player cell is counted as a
   position fallback. A block is never empty, because blocks are built from the pool's own rows,
   so the fold-uniform fallback the foundation uses cannot fire here; the code says so rather
   than carrying a branch for it. The row draw is one `generator.integers(0, high)` call over a
   (scenarios, players) array of option counts.
5. **Unchanged.** The minutes and points residuals of the drawn row stay paired as today. The
   one-minute floor, the `90 * fixture_count` ceiling, the non-clipping of points, the zeroing
   of non-appearances, the seed derivation (`_draw_seed`) and the scenario identity fields are
   unchanged.

Every draw records in `ScenarioSet.diagnostics`: `residual_selection: "team_match_block"`, the
contract version, the number of history folds, the mean number of blocks per fold, the mean block
size in rows, the number of target clubs, the fixture-count fallback count and rate over
scenario-club cells, the blank-club cell count, the position fallback count and rate over
scenario-player cells, and the mixed-fixture block count.

## Control arm

In the same run, on every measured fold, the foundation sampler is drawn on the same table,
decisions, scenario count and seed, and scored by the same scorer. Its `PIT_t`, `q10_t` and `L_t`
are recorded beside the candidate's, with S1 and S2 point readings over the same 137 folds. The
control arm is the comparison; the frozen binding record is quoted.

## Diagnostics recorded per fold (descriptive, deciding nothing)

- Block diagnostics as listed above, pooled over folds as means.
- The within-club correlation of sampled points: for the fifteen selected players, for every pair
  of players sharing a target club, the Pearson correlation across the 1,000 scenarios of their
  `scenario_points` columns (non-appearances enter as zero, which is what the squad score sees);
  the fold value is the mean over pairs, null when the squad has no same-club pair. Reported for
  the candidate and for the control arm on the same fold, and pooled as the mean over folds that
  have a pair, with the number of pairs.
- The scenario standard deviation and `q10_t` of the squad score, candidate against control.
- The paired per-fold differences, candidate minus control, of `L_t` and of `PIT_t`, as a mean
  and a 90% season-aware moving-block bootstrap interval (blocks of four consecutive folds within
  a season, 2,000 resamples, seed 0, `season_aware_moving_block_interval`). Descriptive: the gates
  are read on point estimates, as the binding protocol says, and this interval decides nothing.

## Fidelity precondition

The sampler fidelity diagnostic (`scripts.measure_component_fidelity`) is run on the candidate
first, on the regenerated table, under the same `ScenarioConfig()` defaults, and committed as its
own record, `docs/research/team_match_block_sampler_fidelity.json`, under its own contract
`phase_d_component_fidelity_candidate_v1`. It registers no threshold. The calibration run verifies
it structurally, as the binding protocol defines "verified": it loads under its contract, names
the regenerated table, roster and manifest digests, names the candidate sampler by its contract
version, records the frozen scenario configuration, covers the same 138 measured and 9 excluded
folds, and contains no non-finite reading. Without it the calibration run abstains. Its measured
differences are reported and cannot be used to tune or rescue S1 or S2.

## Runner contract

`scripts.run_component_squad_calibration` and `scripts.measure_component_fidelity` gain a
`--team-match-block` flag that selects the candidate. On the v1 contract a candidate run is pinned
to the three expected digests on the command line, cannot write the binding record's path, is
refused when combined with the conditional-residual flags, carries `binding: false`, and names
the sampler's contract version in `sampler`, `candidate` and every fold record. The binding path,
with no candidate and no expected digests, is unchanged byte for byte.

## Verdict

Read once, on the candidate arm's 137 folds:

- `candidate_within_gates` when S1 and S2 both lie inside their bands.
- `candidate_outside_gates` otherwise.
- `abstained` on any population mismatch, a missing or structurally invalid fidelity record, an
  incomplete realized score or fewer than 137 folds.

The verdict is not softened and the run is not repeated. A re-run after the verdict would replace
a measurement with a different one; a reproduction checks the committed record and replaces
nothing.

The record states the repository's noise floor explicitly: an effect smaller than 1.5 points per
gameweek is not certified. This protocol makes no points claim; the gates are the S1 and S2 bands,
and the floor applies to any points claim the record makes, of which there is none.

## Not measured

Opponent pairing (the two clubs of one fixture drawn together), the captain's second copy,
dispersion scales, location shifts, multi-week paths, and any other sampler. Nothing here reads
2025-26. No timing pilot was run: the binding run took 1,787 seconds on the owner's machine, and
the only additions are a second draw and a second scoring per fold.

## Commits

1. This protocol.
2. The sampler, the runner flags and the tests, committed before any measurement so each record
   names a clean commit.
3. The fidelity record, the calibration record, their Markdown twins, two index rows, the
   catalogue rows and the research guide link.
