# Data Dictionary

Per-column reference for the canonical player-gameweek dataset. Companion to
[the data contract](data_contract.md); constants live in
`src/squadopt/data/schema.py`.

`Known by` answers: at what point is this value fixed for the gameweek in its own
row? `deadline` means it is available when the gameweek `t` decision is made, so a
gameweek `t` feature may read it from row `t`. `post-match` means it only exists
after the gameweek is played, so a gameweek `t` feature may only read it from
earlier rows.

No raw-source mapping is filled in yet: Sprint 0 has no verified external source,
so the `Raw mapping` column stays `—` until an adapter is written against a real
file. Source-specific names are recorded in the adapter, never here.

## Required columns

### `season`
- **Type / unit** — string, e.g. `2025-26`. No unit.
- **Meaning** — Competition season label. Acts as the outer boundary for every
  rolling window, so one season's history cannot flow into another's.
- **Known by** — deadline.
- **Missing policy** — Not allowed. Rejected, never inferred from `gameweek`.
- **Validation** — Present, non-null, non-empty after stripping.
- **Leakage risk** — Low directly, **high if omitted from the group key**:
  dropping it makes rolling windows span season boundaries.
- **Status** — required. Part of the primary key.
- **Raw mapping** — —

### `gameweek`
- **Type / unit** — integer, 1-based. Unit: gameweeks.
- **Meaning** — The target time axis. Ordering key within a player's history.
- **Known by** — deadline.
- **Missing policy** — Not allowed. Rejected.
- **Validation** — Integer, `>= MIN_GAMEWEEK` (1); non-integer or out-of-range
  values are rejected with the offending value reported. An optional upper bound
  comes from validation config, not from a hard-coded competition length.
- **Leakage risk** — Low. Misordering silently corrupts every rolling feature,
  which is why a deterministic sort is applied before any time-dependent step.
- **Status** — required. Part of the primary key.
- **Raw mapping** — —

### `player_id`
- **Type / unit** — integer or string; one consistent type per dataset.
- **Meaning** — Stable player identity. **Survives team transfers**, so a
  transferred player keeps one continuous history rather than being split.
- **Known by** — deadline.
- **Missing policy** — Not allowed. Never synthesized from `name`, which is not
  unique and changes spelling between sources.
- **Validation** — Non-null; integer or non-empty string; consistent type across
  the column; unique within `(season, gameweek, player_id)`.
- **Leakage risk** — None.
- **Status** — required. Part of the primary key.
- **Raw mapping** — —

### `name`
- **Type / unit** — string.
- **Meaning** — Human-readable display name. Presentation only; never used as a
  join or grouping key.
- **Known by** — deadline.
- **Missing policy** — Not allowed. Rejected rather than filled with a
  placeholder, because the optimizer requires a non-empty string.
- **Validation** — Non-null, non-empty after stripping.
- **Leakage risk** — None.
- **Status** — required.
- **Raw mapping** — —

### `team_id`
- **Type / unit** — integer or string; one consistent type per dataset.
- **Meaning** — Club identity for that gameweek. Drives the optimizer's
  maximum-players-per-team constraint.
- **Known by** — deadline. May change across rows for a transferred player; the
  projection for gameweek `t` uses the value in row `t`.
- **Missing policy** — Not allowed. Rejected.
- **Validation** — Non-null; integer or non-empty string; consistent type.
- **Leakage risk** — Low. Reading a *later* row's `team_id` for an earlier
  gameweek would be leakage; reading row `t` for gameweek `t` is not.
- **Status** — required.
- **Raw mapping** — —

### `position`
- **Type / unit** — controlled enum: `GK`, `DEF`, `MID`, `FWD`.
- **Meaning** — Positional role. Drives squad quotas and formation constraints.
- **Known by** — deadline.
- **Missing policy** — Not allowed. Rejected; there is no default position,
  because a wrong one corrupts every positional constraint.
- **Validation** — `normalize_position()` maps recognized aliases (`GKP`,
  `Goalkeeper`, `Defender`, `Midfielder`, `Forward`) case- and
  whitespace-insensitively, and raises on anything else. Platform-specific
  numeric codes are translated in adapters, not here.
- **Leakage risk** — Low; same reasoning as `team_id`.
- **Status** — required.
- **Raw mapping** — —

### `price_tenths`
- **Type / unit** — non-nullable integer. Unit: tenths of a currency unit
  (`5.5 -> 55`, `10.0 -> 100`).
- **Meaning** — Price in effect **for** that gameweek, i.e. the price payable at
  that gameweek's deadline. Adapters must satisfy this semantic; a source that
  reports post-gameweek prices must be shifted at adapter level and the deviation
  documented.
- **Known by** — deadline. This is why the gameweek `t` projection takes price
  from row `t`: the optimizer must spend the price actually payable.
- **Missing policy** — Not allowed. Rejected, never interpolated, because a
  missing value promotes the column to float and the optimizer rejects the table.
- **Validation** — Integer dtype, `>= 0`; negative prices rejected. Conversion
  from a decimal source uses `Decimal(str(value)) * 10` with `ROUND_HALF_UP`,
  matching the optimizer's rounding convention. Binary float arithmetic is not
  used, since `5.5 * 10` is not exactly `55` in binary floating point.
- **Leakage risk** — **Medium.** Carrying a *future* gameweek's price into an
  earlier projection is leakage. Rolling price features, if ever added, are
  pre-match columns and need no shift; price-*change* features must not look
  forward.
- **Status** — required.
- **Raw mapping** — —

### `minutes`
- **Type / unit** — numeric, `>= 0`. Unit: minutes played.
- **Meaning** — Minutes actually played in that gameweek. The main input to any
  expected-minutes signal, which is the dominant driver of fantasy scoring.
- **Known by** — **post-match.**
- **Missing policy** — Not allowed in canonical output. A player who did not
  feature is `0`, which is a real observation, not a missing value. A genuinely
  absent source value is rejected rather than assumed to be zero.
- **Validation** — Numeric, non-null, `>= 0`; negatives rejected.
- **Leakage risk** — **High.** Row `t`'s minutes must never enter a gameweek `t`
  feature. Rolling minutes features are shifted by one gameweek first.
- **Status** — required. Outcome column.
- **Raw mapping** — —

### `total_points`
- **Type / unit** — numeric. Unit: fantasy points.
- **Meaning** — Realized total score for that gameweek. Basis of the baseline
  projection and of the prediction target.
- **Known by** — **post-match.**
- **Missing policy** — Not allowed. Rejected; not defaulted to zero, which would
  be indistinguishable from a real blank gameweek.
- **Validation** — Numeric, non-null, finite. **Negative values are valid** and
  are not clamped: cards and own goals produce genuine negative scores. Clamping
  happens only when producing `expected_points`.
- **Leakage risk** — **Highest.** This is the target quantity. Row `t`'s value
  entering a gameweek `t` feature is the canonical leakage failure. Every rolling
  aggregation is `shift(1)` then windowed.
- **Status** — required. Outcome column.
- **Raw mapping** — —

## Optional columns

Present only when the source supplies them. Same rules apply: no fabrication, and
each is classified for timing.

| Column | Type | Known by | Leakage risk | Notes |
| --- | --- | --- | --- | --- |
| `opponent_team_id` | int/string | deadline | Low | Fixture context for the target gameweek. |
| `is_home` | boolean | deadline | Low | Must not enter a contract column; the optimizer rejects `bool` there. |
| `fixture_difficulty` | numeric | deadline | Low | Only if the source's rating is genuinely pre-match. |
| `goals_scored` | numeric | post-match | High | Shift before rolling. |
| `assists` | numeric | post-match | High | Shift before rolling. |
| `clean_sheets` | numeric | post-match | High | Position-dependent usefulness. |
| `goals_conceded` | numeric | post-match | High | Shift before rolling. |
| `saves` | numeric | post-match | High | Goalkeepers. |
| `bonus` | numeric | post-match | High | Already inside `total_points`; correlated. |
| `yellow_cards` | numeric | post-match | High | Shift before rolling. |
| `red_cards` | numeric | post-match | High | Shift before rolling. |
| `starts` | numeric | post-match | High | Start-consistency signal. |
| `expected_goals` | numeric | post-match | High | Source-provided xG only; never recomputed. |
| `expected_assists` | numeric | post-match | High | Source-provided xA only. |
| `expected_goal_involvements` | numeric | post-match | High | Source-provided only. |
| `selected_by_percent` | numeric | **unverified** | High | Snapshot timing unknown. Excluded from Sprint 0 features. |
| `availability_status` | string | **unverified** | High | Historical snapshots are often recorded after the fact. Excluded from Sprint 0 features. |

## Derived columns

Produced by the feature and prediction layers, not by ingestion. Not part of the
canonical dataset.

| Column | Layer | Definition | Leakage control |
| --- | --- | --- | --- |
| `minutes_last_{n}` | features | Mean minutes over the previous `n` gameweeks | `groupby(season, player_id)` then `shift(1)` then `rolling(n)` |
| `points_last_{n}` | features | Mean `total_points` over the previous `n` gameweeks | same |
| `points_per_90_last_{n}` | features | Shifted rolling points **sum** divided by minutes sum, times 90 | same; missing when no minutes were played in the window |
| `expected_points` | prediction | Baseline projection for the target gameweek | Built only from shifted features; clamped to `>= 0`; finite |

## The prediction label

There is deliberately **no separate target column**. Because every feature on row
`t` is already shifted to use only gameweeks before `t`, the realized
`total_points` on that same row is the honest label for "predict gameweek `t`".

The alternative — a `target_next_gw_points` column holding gameweek `t+1`'s score —
is a valid reparameterization, but it puts two different time shifts in one table.
That is one more thing to get wrong, and it makes the leakage rules harder to
audit rather than easier. A test asserts no `target*` column is ever emitted.

For model development the split is therefore: `X` = the rolling feature columns,
`y` = `total_points`, with a time-ordered (never random) split. Row `t` never
carries information from `t` or later on its feature side.
