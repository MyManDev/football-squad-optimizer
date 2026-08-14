# Production prediction specification

Status: **draft**. The evaluation gates in this document are pre-registered and frozen: they
were written before the production model existed and must not be edited once a comparison
has been run. Everything else is open to revision until the first production PR merges.

This document is the contract between the production prediction pipeline and the rest of the
system. The optimizer, the uncertainty layer and the scenario generator do not read it —
they read `PredictionSnapshot`. This document exists so that a reader can tell what went
into that snapshot and why each input was allowed.

## Model shape

Expected points are produced in two stages rather than one:

```
expected_points = expected_minutes / 90 * expected_points_per_90
```

The reason is that the two quantities fail differently. A first-choice striker who is
injured and a fringe striker who is fit can carry the same recent points-per-90 while having
nothing in common as a selection. Collapsing availability and scoring rate into one
regression forces a single model to explain both, and the residual it produces cannot be
attributed to either. Splitting them also matches how the uncertainty layer already thinks:
residual scale is learned per player, and a player whose variance comes from rotation is a
different object from one whose variance comes from finishing.

Both stages are fitted on the same leakage-safe feature table and on the same chronological
slice. Neither stage may read the target gameweek's outcome.

## Availability is a rule, not a feature

The archive records `status`, `chance_of_playing_next_round` and `news` after the fact. Their
as-of time cannot be recovered, so a coefficient fitted on them would be fitted on
information we would not have held at the deadline. They are therefore excluded from the
model matrix, and the exclusion is mechanical: they never enter the feature builder.

Live capture changes what is knowable, not what is trained. Once we stamp `captured_at_utc`
ourselves and can prove capture preceded the deadline, availability becomes usable at
inference as a documented rule:

- A player the source marks unavailable is removed from the selectable pool.
- A player carrying a reduced chance of playing has expected minutes scaled by that stated
  chance, and the scaling is recorded in the diagnostics rather than folded silently into
  the projection.
- A player with no availability information is treated as available, because absence of news
  is the normal state and treating it as doubt would penalise every unremarkable player.

This asymmetry is deliberate. The rule uses live availability; the model does not learn from
historical availability. Revisiting it requires a source whose historical snapshot timing is
verifiable, which the archive is not.

## Feature inventory and timing classification

Every feature carries a timing class. Pre-match features may be read from row `t`. Outcome
features may only be read from rows strictly before `t`, which is why every aggregation over
them passes through `shifted_rolling_mean` or `shifted_rolling_sum`. Grouping is
`("season", "player_id")` and does not change.

| Feature | Source | Grain | Known at deadline | Missing-value policy | Timing risk |
| --- | --- | --- | --- | --- | --- |
| `price_tenths` | canonical panel, row `t` | player-gameweek | Yes | Non-nullable by contract | None. Price is shifted one gameweek back at ingest, and the first appearance keeps its own price |
| `position` | canonical panel, row `t` | player-gameweek | Yes | Non-nullable by contract | None |
| `team_id` | canonical panel, row `t` | player-gameweek | Yes | Non-nullable by contract | None |
| `minutes_last_w` | shifted rolling mean of `minutes` | player-gameweek | Derived from `< t` only | `NaN` until history exists; never back-filled | Would leak if unshifted. Enforced by the single shift primitive |
| `points_last_w` | shifted rolling mean of `total_points` | player-gameweek | Derived from `< t` only | `NaN` until history exists | As above |
| `points_per_90_last_w` | shifted rolling ratio | player-gameweek | Derived from `< t` only | `NaN` when shifted minutes are zero | As above |
| `prior_seasons_minutes_per_gameweek` | completed earlier seasons | player-season | Yes | `NaN` for a player with no earlier season | Reads only completed seasons, never the current one |
| `prior_seasons_points_per_90` | completed earlier seasons | player-season | Yes | `NaN` for a player with no earlier season | As above |
| `fixture_count` | fixture table, target gameweek | team-gameweek | Yes | Zero for a blank gameweek, stated rather than imputed | Reads the target gameweek's own fixtures only, which are published before the deadline |
| `home_fixture_count` / `away_fixture_count` | fixture table, target gameweek | team-gameweek | Yes | Zero for a blank gameweek | As above |
| `opponent_attack_strength` | our own estimate from shifted results | team-gameweek | Yes | Position-pooled prior for a promoted team with no record | Computed from outcomes strictly before `t`, so it is an outcome aggregation and is shifted |
| `opponent_defence_strength` | our own estimate from shifted results | team-gameweek | Yes | As above | As above |

Deliberately excluded, with the reason rather than an omission:

- `xP` — the archive scrapes it after the match. It is an outcome dressed as a projection.
- `selected_by_percent` — snapshot timing unverified in the archive.
- `status`, `chance_of_playing_next_round`, `news` — see the availability section above.
- `fixture_difficulty` from the source — opaque, source-specific, and its within-season
  stability is unverified. Ingested for provenance, never consumed as a feature. Our own
  strength estimate is used instead because it is reproducible from shifted history.
- `starts`, `expected_goals`, `expected_assists` — present only from 2022-23 onward.
  Adopting them would shorten the training window to four seasons and, more importantly,
  would change the fold set so paired comparison against the existing baseline and Ridge
  benchmarks would no longer be like-for-like. Deferred to its own issue.

## Cold-start precedence

A player with no in-season history is not a single case, and the two stages do not run out
of signal at the same moment. Each stage therefore has its own ladder, and the point where
the two-stage product stops applying is stated rather than left implicit.

### The minutes stage

1. **Current-season appearance history.** How often a player features, multiplied by how
   long when he does.
2. **An observed absence.** History exists and says he featured in none of the recent
   gameweeks, which projects to zero. This is a measurement, not a gap; folding it into the
   fallback would discard a real observation.
3. **Cross-season carry-over**, shrunk toward zero. He has a record, just not this season,
   and last season may no longer describe him — a transfer, a new manager, a different depth
   chart. Shrinking states that uncertainty instead of projecting last season forward
   unchanged.
4. **Nothing.** The estimate is left missing.

### The points stage

1. **Current-season scoring rate** from shifted history.
2. **Cross-season carry-over rate** for a player with a record but not this season.
3. **The fitted opening price prior**, for a player with no record anywhere.

### Where the product stops applying

The two-stage form is `expected_minutes / 90 * expected_points_per_90`, and it is used
wherever both stages have signal.

It does **not** apply at the bottom rung, and that is a correctness point rather than a
convenience. The price prior estimates *expected points* directly — `coefficient *
price_tenths / 10` — not a per-90 rate. Multiplying it by `expected_minutes / 90` would
scale a quantity that already accounts for playing time by playing time a second time,
which double-counts the prior and pushes every genuinely new player toward zero. So for a
player whose minutes stage produced nothing, the price prior supplies `expected_points`
directly and the product is bypassed.

This is why the minutes stage leaves its last rung missing instead of taking a constant.
A fabricated minutes figure would satisfy the formula and silently corrupt the one case the
formula cannot describe. Leaving it missing keeps the two claims separable: "we do not know
how long he will play" and "we estimate his points from price alone" are different
statements, and only the second is one we can defend.

### Guarantees

The final `expected_points` is never missing and never negative. A player who reaches the
end of both ladders without a projection is an error, not a zero.

Which rung fired is recorded per player in the snapshot diagnostics, for both stages.
"We measured this" and "we fell back" are different claims, and a squad built mostly from
fallbacks should be visibly that rather than indistinguishable from a measured one.

The price prior is refitted per fold on an expanding window rather than applied as one
global constant. A constant fitted across all seasons and then used inside earlier folds
would have seen those folds' own opening outcomes. The effect is confined to opening
gameweeks, because walk-forward folds skip them by default, but the fold story should be
uniform regardless.

## Pre-registered evaluation gates

The operational control is the deterministic baseline at `form_window = 5`,
`bench_weight = 0.1`, `risk_aversion = 0`. The Ridge reference is a mandatory second
comparison and does not become the control.

Baseline superiority gate, on the same development folds:

- Mean improvement of at least `+0.5` squad points per gameweek.
- 90% moving-block bootstrap lower bound at or above `0`.

Ridge comparison gate, on the same folds:

- Mean difference at or above `0`.
- 90% lower bound at or above `-0.5`.

Additional conditions, all of which must hold:

- Every fold feasible.
- Every leakage test passing.
- At least one of MAE or RMSE improved against Ridge.
- The other of the two degraded by no more than 5% in relative terms.
- No serious systematic per-position bias.

The observed `+4.8108` Ridge-over-baseline difference from the 2024-25 smoke benchmark is
not a threshold. It is one season's realised result and is recorded here only so that nobody
later mistakes it for a target.

Note what the two gates imply together: because the Ridge gate requires the production model
to match Ridge, the binding constraint in practice will be whatever Ridge actually achieves
across the full development fold set, and the `+0.5` baseline gate will not bind unless
Ridge underperforms there. This is intended, and it is why Ridge is measured across all
development folds before the production model is built rather than after.

## Determinism and provenance

- Input frames are never mutated in place.
- The same input and the same config produce byte-identical output.
- Row ordering is deterministic and does not affect any feature or prediction.
- Training-only imputation and standardisation. Statistics are computed on the training
  slice and applied to the target rows, never the reverse.
- Provenance carries model name, model version, feature contract version, training cutoff
  and training-data fingerprint, and the resulting projection carries a prediction
  fingerprint.

## Known limitations

- Historical postponement is unrecoverable. The archive places a rescheduled fixture in the
  gameweek where it was eventually played, so no "this fixture was postponed" signal can be
  trained. Live capture can observe it; the model cannot learn from it.
- Historical availability is unusable, as set out above. The rule applies from the first live
  capture onward and cannot be validated against past seasons.
- Team strength is estimated from shifted results only, so a promoted team begins each season
  with a pooled prior and is mispriced until it accumulates a record.
