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

### Entry payloads: which capture may be read for whose squad

The rule above is about columns of the canonical panel. The per-entry documents (#127) are
not panel rows, and they need their own statement because the question they answer is
"whose squad was this, when" rather than "was this column knowable".

**A gameweek's picks are frozen at that gameweek's own deadline, not when its fixtures
finish.** So for the gameweek `t` decision, `event/{t-1}/picks` is the squad the manager
holds going in, and it is complete the moment `t-1`'s deadline passes. This is deliberately
a weaker condition than the one `in_season_totals` needs: played *history* requires matches
to have happened, a *squad* does not. The two must not be conflated, because assuming picks
need played fixtures would delay a read that is already valid, and assuming history needs
only a passed deadline would read counters that are still empty (the failure recorded in
issue #224).

**One capture, read twice.** The capture taken after gameweek `t-1` is settled is the same
capture the `t` decision's entry payloads come from. There is no separate fetch moment for
picks, and there must not be one: two captures would mean two different roster states
answering for the same decision.

**Before the opening deadline there is nothing to read.** Gameweek 0 does not exist, so a
capture open for gameweek 1 reads no picks at all rather than reading an empty document.

**The standings page is a membership record, not a schema.** A captured
`league-{id}-standings.json` states who was in the league at that instant. It seeds the
registry; it is not a source of player-gameweek rows and no feature reads it.

Two fields the public endpoints do not publish, and which therefore have to be carried as
declared unknowns rather than filled in:

| Field | State | What a consumer may not claim |
| --- | --- | --- |
| `purchase_prices` | empty, `purchase_prices_known=False` | Not a selling price. A held squad built from these picks values every player at his *current* price, which overstates the budget for anyone who has risen since he was bought. |
| `free_transfers` | `1`, `free_transfers_known=False` | Not the banked count. The endpoints never state it. It is derivable from the per-event transfers and costs, but only through a model of the banking cap (changed in 2024-25) and of the chip weeks that consume no transfer — so it is an open decision, not a parsing detail. |

Both flags exist so a consumer that spends real budget or plans real transfers on these
numbers has to acknowledge the limit rather than discover it.

**The manager's own name is not captured into the registry.** The standings page publishes
it beside the team name; only the team name becomes the registry label, and the registry
itself stays out of git (`.gitignore`) because it is third-party data about identifiable
people and this repository is public.

### Live gameweek points: a running total, and what it is short by

`event-gw{NN}-live.json` carries what each player has scored *so far* in a gameweek that may
still be being played. It exists so a decision can be shown against reality before the
gameweek closes, and it needs its own rule because every reading of it is incomplete in a
way that is easy to miss.

**Bonus is added per fixture, when that fixture finishes.** A score read earlier is short by
up to three points per player, and short by *different* amounts for different players — so
it is a biased number, not a noisy one, and it does not average out across a squad. This is
why `bonus_confirmed` travels with the points and is false until every one of the gameweek's
fixtures is finished. Nine of ten finished is not "basically final".

**The live document names no gameweek.** Its whole body is `{"elements": [...]}`; the
platform identifies it only by the URL it was fetched from. The adapter therefore cannot
verify that a payload named for gameweek `N` describes gameweek `N`, and does not pretend
to. What it can state is that gameweek's own progress, which is why the fixtures payload is
a required second argument and `fixtures_finished` / `fixtures_total` are reported beside
the points.

**These points are never a settled outcome.** A ledger outcome is immutable — the ledger
refuses a second write for a gameweek that already has one. Recording a pre-bonus figure
through that path would therefore permanently prevent the real settle from ever being
recorded. Live points may be *derived into a view*; they may not be written as an outcome.

**Automatic substitutions are not applied here — but their inputs are read.** This payload
yields points *and minutes* per player. Which eleven those points are counted for belongs to
the ledger, which scores the eleven that were **named** because that is what the projection
was for; the platform's own score replaces a starter who played no minutes and is a second,
equally real number (#262). Supplying an input is not applying a rule, and keeping the two
apart is what lets one caller score the named eleven and another the platform's from one
reading of one payload.

**Minutes come from this document and not from `bootstrap-static`.** The bootstrap's
`minutes` is season-cumulative: it equals the gameweek's for gameweek one and for no other,
because that is the only gameweek with nothing behind it. Reading it as a per-gameweek figure
would be right once and silently wrong from gameweek two onward. The two mappings must also
cover exactly the same players, and the adapter refuses a payload where they do not — a
player whose minutes went missing reads as *did not play*, which is how a substitution gets
fabricated for someone who was on the pitch. For the same reason a `stats` object with no
`minutes` key is refused rather than defaulted to zero, and no upper bound is imposed: a
double gameweek legitimately reaches 180.

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
