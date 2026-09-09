# Member planning policy: transfer hit cost grid

Lookahead-1 season chain, chips off (the member path's planner offers no chip unless the
operator names one), five seasons with 2025-26 walked as declared development data
(`--development-scope v2`), deterministic budget 8 per solve. The game charges 4 per
extra transfer on every sheet; the planner's hit cost above 4 is a caution margin on
projected gains, not a rule change.

## Season nets by planning hit cost (net of the game's 4-point hits)

| Season | hit 4 | hit 5 | hit 6 | hit 7 | hit 8 |
| --- | ---: | ---: | ---: | ---: | ---: |
| 2021-22 | 1994 (hits 216) | 1957 (hits 180) | 1942 (hits 116) | 1983 (hits 76) | 2020 (hits 64) |
| 2022-23 | 2013 (hits 188) | 2076 (hits 124) | 2056 (hits 84) | 2076 (hits 60) | 2077 (hits 44) |
| 2023-24 | 1724 (hits 144) | 1771 (hits 96) | 1780 (hits 72) | 1855 (hits 32) | 1846 (hits 24) |
| 2024-25 | 1919 (hits 124) | 2001 (hits 84) | 1972 (hits 60) | 2021 (hits 16) | 2011 (hits 12) |
| 2025-26 | 1657 (hits 100) | 1731 (hits 52) | 1756 (hits 28) | 1761 (hits 12) | 1802 (hits 4) |

## Pooled net points per week and the paired comparison with hit cost 4

| Hit cost | Net/week | Mean season net | Mean season hits | Season spread | vs 4: weekly mean | 90% interval | Season delta by season | Worse seasons | Rule |
| ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: | --- |
| 4 | 50.58 | 1861.4 | 154.4 | 356 | — | — | — | — | baseline |
| 5 | 51.83 | 1907.2 | 107.2 | 345 | +1.24 | [+0.34, +2.18] | 2021-22 -37, 2022-23 +63, 2023-24 +47, 2024-25 +82, 2025-26 +74 | 1 | passes |
| 6 | 51.66 | 1901.2 | 72.0 | 300 | +1.08 | [-0.13, +2.02] | 2021-22 -52, 2022-23 +43, 2023-24 +56, 2024-25 +53, 2025-26 +99 | 1 | fails |
| 7 | 52.70 | 1939.2 | 39.2 | 315 | +2.11 | [+0.83, +3.44] | 2021-22 -11, 2022-23 +63, 2023-24 +131, 2024-25 +102, 2025-26 +104 | 1 | passes |
| 8 | 53.02 | 1951.2 | 29.6 | 275 | +2.44 | [+1.04, +3.94] | 2021-22 +26, 2022-23 +64, 2023-24 +122, 2024-25 +92, 2025-26 +145 | 0 | passes |

## Decision

Rule (declared before the run): change the default only if a level beats 4 in pooled mean weekly net AND its 90% interval excludes zero AND it is not worse than 4 in more than one season.

Levels passing: [5, 7, 8]; the best of them by pooled weekly mean is **8**.

The rule fires, and the pull request that recorded this measurement (#401) still shipped
`member_planning_policy_v1` at hit cost 4. Acting on the reading was a second change,
because it moves what every league member is told.

**Acted on in #405.** The owner chose 8. `member_planning_policy_v2` plans at 8; the
new `hit_points_charged` control keeps the game's 4, and every hit a member is shown,
every hit the ledger records, and every comparison between two solved plans is counted
at the charge. 8 is the top of this grid, so it sits on an edge rather than at an
interior optimum: the next measurement should widen the range (4-12) before it is read
as one.

## What this does and does not say

- **It disagrees with `transfer_discipline` (2026-08-17), and not only because of the
  fifth season.** That measurement walked the chain with chips under the reservation
  rule and found hit cost 6 and 8 *worse* than 4 (-29 and -27 mean season net); this one
  walks it with **chips off**, which is what the member path actually does -- it offers no
  chip unless the operator names one. Chip mode is a real difference in configuration, so
  the two readings are not the same experiment run twice, and the older verdict is not
  overturned on its own terms. 2021-22, the season that carried that artifact's negative
  (-236 at hit 6), is only -52 here and turns +26 at hit 8.
- **2025-26 is declared development data**, the Phase C v2 scope: a season this repository
  has used before. Its cells are development evidence and are not an unseen final test.
- **The gain is mostly hits not paid.** Paid transfers fall from 193 across the five
  seasons at cost 4 to 37 at cost 8, and season hit points from 154 to 30 on average. The
  reading is consistent with the discipline note's own diagnosis -- the projection's early
  weeks are optimistic, so a paid transfer bought on them tends to lose -- and a caution
  margin is a way of not paying for that optimism, not a claim that the game charges more.
- **One projection rule, one solver budget, five seasons.** Deterministic budget 8 per
  solve; proven share 0.972 to 1.000, so the solves are
  essentially all proven and the differences are not solver noise. The interval is a
  season-aware moving-block bootstrap on 184 paired gameweeks; a season is still one
  observation, and five is not many.

## Standing of the record itself

The numbers above moved a live planning control, so what this record does and does not
establish is written down rather than inferred. Nothing here re-runs the measurement or
edits the artifact after the fact; the artifact is left exactly as it was written.

- **It is reproducible, and this is the command.** The artifact's provenance names
  repository commit `0b9e0ecc4097…`, which resolves in this repository and is #401's own
  commit, "feat(scripts): let the season chain take a planning hit cost and the v2
  development scope". `git diff 0b9e0ec..HEAD -- scripts/run_season_chain_seasons.py
  src/squadopt/experiments/season_chain_runs.py` is empty, so the runner that produced the
  cells is byte-identical to the runner on `develop` today. One cell is

  ```console
  python -m scripts.run_season_chain_seasons --seasons <SEASON> --development-scope v2 \
    --lookaheads 1 --chips off --hit-cost <COST> --deterministic-time-limit 8
  ```

  run once per season and hit cost — the 25 cells the timing section below lists.

- **The statistics are repository code; the wrapper around them is not.** The per-cell
  chain and the paired comparison come from the committed `season_chain_runs` /
  `chain_comparison` code, with the bootstrap parameters the artifact records. What is
  local is the driver that ran the 25 cells and assembled them into one document, which is
  what the artifact's own `contract_version` announces by ending in `_local_v1`: no code in
  this repository writes this schema, so regenerating the *document* means re-running the
  cells and reassembling them, not calling one script.

- **No measurement kind covers it, so no preflight applies.**
  `squadopt.preflight.measurement.MEASUREMENT_KINDS` registers eight kinds and none of them
  describes a season-chain grid, and `tests/unit/test_measurement_preflight.py` gates five
  named artifacts, none of this family. `scripts.run_measurement_preflight` therefore has no
  kind to run this file under. That is an absence of a gate, not a gate it fails; running it
  under a kind meant for a different artifact family fails on that family's required fields
  and says nothing about this one.

- **Its provenance encoding is non-standard, and that is the one real defect here.**
  `repository_commit`, `archive_commit`, `archive_manifest_sha256` and `working_tree_dirty`
  are stored as one-element lists holding JSON-encoded strings — `["\"0b9e0ecc…\""]`,
  `["false"]` — and this is the only committed artifact of the 92 in `docs/` whose core
  provenance fields are not plain scalars. A reader matching on shape cannot read them, and
  a truthiness test on `working_tree_dirty` inverts: the list is truthy while the value it
  encodes is `false`, i.e. the tree was **clean**. Decoded by hand every value resolves —
  the repository commit is above, the archive commit is the `ARCHIVE_COMMIT` 75 other
  committed artifacts record, and the manifest digest matches four of them. Any future
  regeneration should write these as bare strings and a JSON boolean.

- **Two self-descriptions in the artifact went stale when #401 committed it.** The JSON
  carries `"committed": false`, and this file used to be titled "(local, not committed)",
  from the run that produced them; the file was then committed and indexed. No code reads
  the `committed` key — it appears in no module under `src/`, `scripts/` or `tests/`, and
  no other artifact carries it — so the stale value decides nothing. The title is corrected
  here; the artifact's own field is left untouched, because hand-editing a measurement
  artifact after the fact is worse than a stale field that is written down.

- **`policy_id` names the policy in force when the run happened**, `member_planning_policy_v1`
  at hit cost 4, while the sibling `decision` block records the pre-declared *rule's*
  verdict. Those are not in conflict: the rule fired, #401 still shipped v1 at 4, and acting
  on the reading was the separate later change recorded above.

- **What it does not establish.** The 90% block-bootstrap intervals cannot be re-derived
  from this record alone: that needs the per-gameweek paired series, which ADR 0003 keeps in
  the gitignored evidence tier. The method, the resample count, the block length and the
  paired-gameweek count are recorded; the underlying weekly arrays are not. And the grid is
  five seasons of one projection rule at one solver budget — a season is one observation.

## Timing

25 cells, 4 workers, 1116 s wall in total; per cell 2025-26/hit4 195s, 2025-26/hit5 226s, 2025-26/hit6 212s, 2025-26/hit7 169s, 2025-26/hit8 199s, 2021-22/hit4 206s, 2021-22/hit5 270s, 2021-22/hit6 234s, 2021-22/hit7 239s, 2021-22/hit8 192s, 2022-23/hit4 153s, 2022-23/hit5 183s, 2022-23/hit6 141s, 2022-23/hit7 130s, 2022-23/hit8 121s, 2023-24/hit4 123s, 2023-24/hit5 124s, 2023-24/hit6 131s, 2023-24/hit7 116s, 2023-24/hit8 129s, 2024-25/hit4 154s, 2024-25/hit5 143s, 2024-25/hit6 143s, 2024-25/hit7 116s, 2024-25/hit8 116s
