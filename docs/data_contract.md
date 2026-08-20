# Data Layer Contract

Owner: data / data mining. Status: **frozen for Sprint 0**.

This document defines the two schemas the data layer guarantees. Internal
implementation may change freely; changing anything below requires coordination
with the optimization and software owners.

`src/squadopt/data/schema.py` is the executable form of this document. Where the
two disagree, the module is authoritative and this file is a defect.

## 1. Canonical player-gameweek dataset

One row is one player in one gameweek of one season.

**Primary key:** `(season, gameweek, player_id)` — unique, no nulls.

### Required columns

| Column | Type | Rule |
| --- | --- | --- |
| `season` | string | Non-empty. Rolling-window boundary. |
| `gameweek` | integer | `>= 1`. Optional upper bound supplied by validation config. |
| `player_id` | integer or string | Non-null. One consistent type per dataset. Stable across team transfers. |
| `name` | string | Non-empty display name. |
| `team_id` | integer or string | Non-null. One consistent type per dataset. |
| `position` | enum | Exactly `GK`, `DEF`, `MID`, `FWD`. |
| `price_tenths` | integer | `>= 0`. Integer tenths: `5.5 -> 55`, `10.0 -> 100`. |
| `minutes` | numeric | `>= 0`. |
| `total_points` | numeric | **May be negative** (cards, own goals). Not clamped. |

### Optional columns

Carried through only when the raw source actually provides them, under the
canonical names listed in `OPTIONAL_COLUMNS`. Missing optional fields are never
fabricated, imputed, or defaulted into existence.

`opponent_team_id`, `is_home`, `goals_scored`, `assists`, `clean_sheets`,
`goals_conceded`, `saves`, `bonus`, `yellow_cards`, `red_cards`, `starts`,
`expected_goals`, `expected_assists`, `expected_goal_involvements`,
`selected_by_percent`, `availability_status`, `fixture_difficulty`

Unrecognized source columns are dropped rather than silently renamed. Mapping a
platform-specific name onto a canonical name is an explicit adapter decision.

### Ordering

Canonical output is sorted by `CANONICAL_SORT_COLUMNS` = `(season, gameweek,
player_id)` with a reset index. Output is independent of input row order.

## 2. Optimizer-ready projection table

One row is one player, for a single target gameweek. This is the only table the
optimizer consumes, and it must satisfy `squadopt.optimization.validation`.

| Column | Rule enforced downstream |
| --- | --- |
| `player_id` | Unique, non-null; integer or non-empty string, one type per column |
| `name` | Non-empty string |
| `team_id` | Non-null; integer or non-empty string, one type per column |
| `position` | Exactly `GK`, `DEF`, `MID`, `FWD` |
| `price_tenths` | Integer, `>= 0` |
| `expected_points` | Finite, numeric, **`>= 0`** |

The column tuple is imported from the optimizer as `PROJECTION_REQUIRED_COLUMNS`
rather than restated, so the two sides cannot drift. A test locks the expected
value, so an upstream change fails loudly instead of silently.

### Three constraints that are easy to get wrong

1. **`price_tenths` must be a true integer dtype.** The optimizer checks each
   element against `numbers.Integral`, not the column dtype. A single missing
   value promotes the column to `float64`, every element becomes `float`, and the
   whole table is rejected. `pd.NA` in a nullable `Int64` column fails for the
   same reason. Canonical output therefore uses non-nullable integers.
2. **`expected_points` must be non-negative.** Realized `total_points` can be
   negative, but a *projection* may not be. The baseline clamps at zero.
3. **`bool` is rejected everywhere.** Flags such as `is_home` must not land in a
   contract column.

Extra columns are preserved by the optimizer and ignored by its decision logic,
so the projection table may carry diagnostic columns.

## 3. Time-of-knowledge rule

For target gameweek `t`, a feature or projection may read:

- **pre-match columns** from rows up to and including `t`;
- **outcome columns** from rows strictly before `t`.

Row `t` is not uniformly unknowable. Identity, team, position, price, and fixture
context are fixed at the gameweek `t` deadline; minutes, points, and every match
statistic only exist afterwards. Treating the whole row as forbidden would
wrongly deny the optimizer the price it must actually pay.

| Class | Constant | Columns |
| --- | --- | --- |
| Pre-match | `PRE_MATCH_COLUMNS` | `season`, `gameweek`, `player_id`, `name`, `team_id`, `position`, `price_tenths`, `opponent_team_id`, `is_home`, `fixture_difficulty` |

`fixture_difficulty` is the one entry whose pre-match claim depends on the **source**, and
the classification cannot say so because it is per column: `is_outcome_column` is given a
name, never a row. A live capture proves the instant it was read; the archive publishes no
capture instant, and its single per-season file was written after the season finished — the
difficulty integer shares a row with that fixture's final score, and the same directory's
`teams.csv` carries the final table. So the archived value is not what the platform
published in August, and it is not admissible as a pre-match feature on development seasons.

The claim is therefore enforced where the source *is* visible:
`attach_fixture_features` refuses to attach `mean_fixture_difficulty` and
`minimum_fixture_difficulty` from fixture rows with no `captured_at_utc`, and offers no
option that attaches them anyway. The raw `fixture_difficulty` column stays on the fixture
table, which is where the provenance studies that examine the archived value read it from.
The fixture **counts** are unaffected: a calendar cannot be contaminated this way.
| Outcome | `OUTCOME_COLUMNS` | `minutes`, `total_points`, `goals_scored`, `assists`, `clean_sheets`, `goals_conceded`, `saves`, `bonus`, `yellow_cards`, `red_cards`, `starts`, `expected_goals`, `expected_assists`, `expected_goal_involvements` |
| Unverified | `AMBIGUOUS_TIMING_COLUMNS` | `selected_by_percent`, `availability_status` |

`is_outcome_column()` classifies a column and **raises** for anything
unclassified, so adding a canonical column forces an explicit timing decision.
Unverified columns count as outcome columns and are excluded from Sprint 0
features until a real source's snapshot semantics are inspected.

The classification is asserted to be a complete, disjoint partition of the
canonical schema, so the leakage rules cannot develop a silent hole.

## 4. Guarantees

- Public transformations copy; no input `DataFrame` is mutated in place.
- Same input and config produce byte-identical output; shuffling input rows does
  not change output.
- No randomness in the Sprint 0 data path.
- Validation errors name the offending column, key, and example values.
- Data-layer exceptions derive from `DataError` and are disjoint from
  `SquadOptimizationError`, so a data fault is never mistaken for a solver fault.

## 5. Explicit non-guarantees

- No claim about predictive accuracy. The baseline exists to make the pipeline
  deterministic and testable.
- No live fetching, scraping, or API integration.
- Single target gameweek only; no transfer or multi-gameweek planning.
- No handling of doubled or blank gameweeks (a player appearing twice, or not at
  all, in one gameweek). The key rejects duplicates; fixture-level modelling is
  later work.
