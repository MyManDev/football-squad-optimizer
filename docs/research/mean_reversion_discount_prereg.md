# Pre-registration: a mean-reversion discount for the later weeks of a multi-week plan

Status on the day this was frozen: protocol fixed, no number of the measurement seen. The
record that fulfils it is `docs/research/mean_reversion_discount.{json,md}`, written by
`scripts/measure_mean_reversion_discount.py`; its row in the
[measurements index](../measurements_index.md) is the current state. Measurement only,
nothing promoted. Nothing in this document (gates, grid, populations, seeds, budgets) changes
after any number of the measurement is seen.

## The question

The multi-week planner's later weeks repeat the decision week's projection, scaled by that
club's fixture count (`naive_calendar_scaling_v1` in
`src/squadopt/experiments/multi_gw_rehearsal.py`, and the same rule in the live member
windows per `WINDOW_STATED_LIMITS` in `src/squadopt/application/advice.py`).
[The rolling-horizon reading](../planner_horizon_rolling_note.md) found that a rolling
three- and four-week planner loses to the weekly control through transfer churn: a far week
whose only difference from today is a double gameweek looks worth a transfer now, and the
optimism at the top of the ranking ([selection optimism](../selection_optimism.md)) makes
such a projected gain clear the hit cost on paper. [The transfer-discipline
reading](../transfer_discipline_note.md) found that a one-transfer cap removes the churn and
leaves the capped rolling three-week planner level with the weekly control.
[The planner control screen](../planner_doe.md) found that the existing
`horizon_discount_factor`, a scalar on every later week's whole objective, changes no
decision at 0.9.

The candidate here is different in kind: a discount on the later weeks' deviation from the
position mean, so a far week's ranking regresses toward the mean while its level stays. It
targets the churn mechanism directly, because what makes a far week look worth a transfer is
its ranking and not its level.

## The candidate rule

`mean_reversion_discount_v1`, a third projection rule of the laboratory chain beside
`naive_calendar_scaling_v1` and `control_calendar_blind_v1`, with one parameter, the
mean-reversion factor `rho` in (0, 1]. For a horizon week at offset `k` from the decision
week (`k = 0` is the decision week and is untouched):

```
m_pos             = mean of the decision-time projection's expected_points over every
                    projected player of that position (the full projection table at the
                    decision gameweek, not the candidate pool)
base_k            = m_pos + rho**k * (expected - m_pos)
expected_points_k = max(0, base_k) * fixture_count(gameweek, team)
```

A blank week stays zero through the fixture count, as today. At `rho = 1` the rule is the
naive rule exactly. The two existing rules keep their arithmetic byte for byte, and a test
holds them to a frame built with the old arithmetic. The chain's week record carries
`m_pos` per position for every decision made under the rule, so a reader can check the
shrink target.

One consequence of the formula is declared here rather than discovered later. A squad member
the chain carries at a zero projection in the decision week, because their club is blank
that week or the archive has no row for them, is worth `m_pos * (1 - rho**k)` times the
fixture count in a later week under the candidate rule, where the naive rule keeps them at
zero in every week. The record counts such carried rows (`carried_blank_rows`,
`carried_unexplained_rows`); they are not removed from either arm.

## Seasons and data

- 2021-22, 2022-23, 2023-24, 2024-25 and 2025-26, from the pinned archive
  (`data/raw/vaastav-fpl`, archive commit `8c97b2adb123863c3dd581e730f1360e89815ac2`),
  each walked once as a chain from its first decision gameweek (the season's second
  gameweek) to its last, state carried, as [the season chain](../season_chain.md) does.
- 2025-26 is read under `--development-scope v2` as declared development data, the scope
  Phase C v2 declared. It is never an unseen test, and the record says so in the words the
  repository already uses (`development_scope: v2`, `locked_holdout_accessed: true`).
- The free-transfer bank cap is the chain's per-season assumption: 2 in 2021-22, 2022-23
  and 2023-24; 5 in 2024-25 and 2025-26 (`MAX_FREE_TRANSFERS` and its default in
  `squadopt.experiments.season_chain_runs`).

## Planner configuration, every arm

The member planning policy (`MEMBER_PLANNING_POLICY` in `src/squadopt/live/transfers.py`),
as far as the chain expresses it:

- planning hit cost 8.0 (`transfer_hit_cost_points`), `hit_points_charged` 4.0 on the
  planner and on the chain's sheet;
- no banked transfer value, `horizon_discount_factor` 1.0;
- chips off (no chip windows, no holding values);
- sell-on fee halved (the game's sell rule);
- pool rule and form window as the committed chains: top 20 plus the cheapest 8 per
  position, form window 5;
- deterministic solver budget 8.0 per solve with the wall clock raised to 60 s so the budget
  binds (`--deterministic-time-limit 8`, as the committed chains).

## Arms

| Arm | Lookahead | Projection rule | Transfer cap |
| --- | ---: | --- | --- |
| `L1` | 1 | `naive_calendar_scaling_v1` | none (the live one-week plan has none) |
| `L3_naive` | 3 | `naive_calendar_scaling_v1` | one transfer a week, a second from two banked free transfers |
| `L3_mr_0.75` | 3 | `mean_reversion_discount_v1`, rho 0.75 | as `L3_naive` |
| `L3_mr_0.9` | 3 | `mean_reversion_discount_v1`, rho 0.9 | as `L3_naive` |
| `L3_mr_0.6` | 3 | `mean_reversion_discount_v1`, rho 0.6 | as `L3_naive` |

The three-week cap is the member window's (`max_transfers_per_gameweek` 1 with
`allow_two_free_transfers` True; `WINDOW_TRANSFER_CAP_LIMIT` and `WINDOW_FREE_PAIR_LIMIT`
in `application/advice.py`). The primary rho is 0.75. The secondary rho values 0.9 and 0.6
are reported beside it; there is no selection among the three after the fact.

## Primary comparison

`L3_mr_0.75` minus `L3_naive`, realized points net of charged hits, paired per gameweek
over the five chains. Interval: 90% season-aware moving-block bootstrap on the per-gameweek
paired differences, blocks of four consecutive weeks, 2,000 resamples, seed 0
(`squadopt.experiments.season_chain_runs.chain_comparison` through
`squadopt.evaluation.statistics.season_aware_moving_block_interval`). Season nets are
reported per arm and per comparison.

## Secondary comparisons

- `L3_mr_0.75` minus `L1`.
- `L3_naive` minus `L1`: the repository's earlier reading, now under the member policy and
  with 2025-26.
- `L3_mr_0.9` and `L3_mr_0.6` against both baselines, reported beside the primary.

Each comparison is decomposed into selection (realized points before hits) and hits, as
[the rolling-horizon reading](../planner_horizon_rolling_note.md) does. Per arm and season
the record reports transfers, paid transfers, reversals (a player transferred in and
transferred out again at a decision at most three gameweeks later; the opening squad is not
a purchase), the proven share of solves and the mean relative gap of the unproven ones.

## Gate

The candidate is **certified** if all three hold:

1. the primary mean paired gain is at least +1.5 points per gameweek;
2. the primary 90% interval excludes zero;
3. the candidate's season net is lower than `L3_naive`'s in at most one of the five seasons.

Otherwise the verdict is **measured, not certified**, reported as measured, with no
softening and no re-run. The noise floor is 1.5 points per gameweek: an effect smaller than
that is not certified whatever its interval. The gate is read once, from the primary
comparison only; the secondary rho values do not enter it.

## What a pass licenses, and what a fail licenses

A pass licenses a proposal, not a change: to carry the rule into the live window builder,
under a separate pre-registration on the operational projection and the member windows. A
fail licenses the record. Neither outcome moves a product default; `live/`, `planning/`,
`optimization/`, `prediction/` and `scenarios/` are not touched by this measurement.

## What is not measured

The experimental football model's per-fixture forecasts, chips, the observed or expected
lineup routes, any member's squad, prices and price changes, automatic substitutions, and
the two existing rules' own worth. The projection is the deterministic baseline of the
chain; the measurement is of the planning mechanism under it, not of projection quality.

## Timing pilot

Before this document was committed, one pilot sized the grid: season 2024-25, the first
eight decision gameweeks (gameweeks 2 to 9), all five arms, deterministic budget 8.0, one
process, on the machine that runs the measurement (4 logical cores). It was run by
`scripts.measure_mean_reversion_discount --seasons 2024-25 --pilot-gameweeks 8`, which
writes only under `artifacts/`. Its log printed each arm's eight-week net total beside its
timing; nothing in this protocol was set from those totals, the arms, the rho grid and the
gate having been fixed before the pilot ran, and the pilot's artifact is not merged into the
record. Seconds per decision: `L1` 1.8, `L3_naive` 10.1, `L3_mr_0.75` 10.9, `L3_mr_0.9` 10.4, `L3_mr_0.6` 10.3 (the three-week arms proved 62% to 75% of their solves inside the budget). At that rate the full grid of five seasons
and five arms, run as one process per season in parallel, is expected to finish in about
one to two hours (about 27 minutes of single-process work per season of 37 decisions, five
processes sharing four cores), well inside the ten hours at which the protocol would have dropped rho 0.6. The
grid is therefore the full one above.

## Procedure

1. Commit this protocol.
2. Commit the rule, the runner and their tests.
3. At that clean commit, run one process per season with `--development-scope v2` and the
   default `--rhos 0.75,0.9,0.6`, each to its own artifact under
   `artifacts/mean_reversion_discount/`, then `--merge` the five into the record. The merge
   writes the per-week expansion to `artifacts/mean_reversion_discount/weeks.json` and
   records its sha256; the committed JSON holds per-season and per-arm totals, the paired
   comparisons with intervals, the decomposition and the solver record.
4. Commit the record, its Markdown twin, the index row, the catalogue row and the link from
   the research guide. If the code changed between the run and the record, the record says
   exactly what changed and why the numbers stand, or the run is repeated.

[Research guide](README.md).
