# A positional structure for goalkeepers and defenders: protocol

Written on 2026-09-20, **before any of it is fitted**. The population, the candidate, the
fitters, the three clauses of the gate and the drop rule are fixed here so that none of them can
be adjusted once the numbers arrive. Tracking issue: #712. It is Route C of
`docs/opponent_rating_handoff.md`, which named it and left it unbuilt.

## Why this group

Two records, measured independently, put goalkeepers in the same place.

- `participation_calibration`: goalkeepers are the worst-calibrated slice of
  `q_start_given_appearance` by a distance, 738 rows predicted **0.8921** against **0.9864**
  observed, a bias of -0.0943, against defenders at -0.0349, midfielders at +0.0338 and
  forwards at +0.0535 (`docs/participation_calibration.json`). Keepers are the worst by
  magnitude, and forwards rather than midfielders are the next largest, which the first draft of
  this document left out.
- `projection_level_audit`: over each decision's top forty per position, goalkeepers read a
  bias of **+0.219 points a row**, and its separate conditional reading, over the keepers who
  appeared, is **+0.472 points a row**. Both are points a row; what differs is the row set, the
  second being the appeared subset of the first. They are **not** a decomposition of one another,
  which that record forbids, and two earlier drafts of this document got this wrong in two
  different ways: first by calling the second a share of the first, then by calling them
  different units. The units are the ones the record's own column headings state
  (`docs/projection_level_audit.md`): the level and the conditional side are points a row, and it
  is the who-plays side that is appearances a row.

A goalkeeper who appears has almost certainly played ninety minutes, and part of his appearance
is priced as a substitute's. The same shape applies to a defender for a different reason: his
points are not a smooth function of a rate. They are an appearance, plus four for a clean sheet,
plus bonus, and a model that multiplies a form rate by an ease factor represents none of that.

`TeamRating.clean_sheet_probability` already emits a probability rather than a scale, so the
object this needs exists.

## What is already measured, and what it does not settle

`opponent_projection_study` measured the **adjustment** shape, a rate scaled by a signal, and
failed: over 110 folds the rating candidate improved error by 0.0016, worsened ordering by
0.00025 and lost 0.909 points a decision. Its per-position coefficients are the reason this
document exists rather than a successor to that one: the slope came out **positive for GK
(+0.2624) and DEF (+0.2276)** and negative for MID (-0.0406) and FWD (-0.0418). The adjustment
failed pooled while pointing one way on this group.

That is a reason to test a different model on this group, not a reason to expect it to pass. A
positive slope in a failed pooled candidate is the weakest kind of encouragement and is recorded
here as such.

## The candidate, fixed

For goalkeepers and defenders only:

```
long(row) = 1 if expected_minutes_if_appearance >= 60 else 0
expected points = appearance_probability
                  x ( (1 + long) + 4 x long x P(clean sheet) + bonus(position) )
```

- **P(appearance)** is the shipped component model's own `appearance_probability`, unchanged and
  not refitted. This candidate replaces the conditional points term and nothing else.
- **`long`** is an indicator on the shipped scalar `expected_minutes_if_appearance`, one when it
  reaches sixty and zero below. **There is no distribution to take a probability from**: the
  model carries a point estimate (`prediction/minutes.py`, and `production.py` divides expected
  minutes by the probability to recover it), so `P(60+ | appearance)` names an object that does
  not exist and an earlier draft of this document used it. The indicator is crude and it is
  **fixed here with its alternatives named and refused**: `q_start_given_appearance` would import
  the very bias this study exists to close (0.8921 predicted against 0.9864 observed for
  keepers), `min(expected minutes / 90, 1)` is a proportion and not a threshold, and the
  archive's `starts` cannot be walked forward onto the first judged season. That last needs its
  source, because an earlier draft stated it wrongly: `merged_gw.csv` **does** carry a `starts`
  column in all three judged seasons and carries none in either training season (checked in
  `data/raw/vaastav-fpl/data/<season>/gws/merged_gw.csv`), and for 2022-23 the column is present
  but unpopulated for gameweeks 1 to 15, summing to zero beside about 19,700 minutes a gameweek,
  which is why `data/sources/vaastav.py` omits that season whole rather than a third of it. So
  the first judged season has no fitted label and neither training season has one at all. Over goalkeeper rows the
  choice moves the appearance term between 1.0 and 2.0 points, which is larger than the bias the
  study is about, so it may not be left to the runner.
- **Appearance points** are the game's: `1 + long`, one for appearing and two at sixty minutes.
- **The clean-sheet term is paid only when the sixty minutes are**, `4 x long x P(clean sheet)`.
  The game pays a goalkeeper or defender four points for a clean sheet at sixty minutes and
  nothing below it, so multiplying by the appearance probability alone would pay a twenty-minute
  substitute in full. An earlier draft did that.
- **P(clean sheet)** is `TeamRating.clean_sheet_probability(club, opponent, is_home=...)`, whose
  three arguments come from the fixture table of the row's own season and gameweek, joined on the
  row's club: the opponent and the venue are the fixture's, and a row whose club has no fixture
  that gameweek is dropped with the double-gameweek rows and counted beside them. It is used
  after the recalibration
  `fit_clean_sheet_calibration` already performs, walked forward over the seasons before the
  judged one and never the judged one itself. **The recalibration is not optional and is fixed
  here**: the handoff records that the raw probability breaks at the top of its range, promising
  better than an even chance on 40 judged fixtures where the clean sheet happened a third of the
  time (0.534 against 0.325). An uncalibrated by-product may not price a defender.
- **`bonus(position)`** is the per-position mean realized bonus **over appeared rows**, fitted on
  the same walk-forward split. Not over clean-sheet matches: a mean taken on clean sheets and
  then added to every row would over-price every defender, in the same direction the level audit
  already finds keepers mispriced. An earlier draft did that too.

Nothing else enters. Goals conceded, saves, attacking returns and cards are **deliberately
excluded**, and this is a real limitation rather than a simplification: the candidate prices only
the part of a defender's points that the structure names. The record will say so, and a failure
on that account is a failure of this candidate and not a licence to add terms and re-run.

**And the structure is dated.** 2026-27 introduces defensive-contribution points, which make a
clean sheet a smaller share of a defender's points than it was in any season judged here. So a
candidate built on this structure and fitted on these seasons would arrive already out of date
for the season it would be used in, and that cannot be added to this document later either. What
a pass here would establish is that the **shape** prices the group better on the seasons the
archive holds; whether it still does under the new rule is a separate question with its own
population, and the live season is the only place it can be asked.

## The population, fixed

- Rows: goalkeeper and defender rows of the `phase_c_component_oof_v1` out-of-fold table, which
  is the model that decides today.
- Seasons judged: **2022-23, 2023-24, 2024-25**, fitted walk-forward on strictly earlier seasons.
- Target gameweeks 4 and later, so at least three gameweeks stand behind any season-to-date term.
- **Fitted on strictly earlier seasons**, which for 2022-23 means 2020-21 and 2021-22, for
  2023-24 adds 2022-23, and for 2024-25 adds 2023-24. A judged season whose training rows number
  fewer than **200 appeared goalkeeper and defender rows** is not judged, and the record says so
  rather than quietly shortening the population; the number is fixed here and, on the counts
  above, is not expected to bind.
- The locked **2025-26 holdout is not read**, and the record carries that as a computed flag.

## The gate, fixed

Three clauses. All three must pass.

### The lesson this gate is built around

`opening_two_part` passed an ordering clause read over a population that is two thirds players
who never appear, and on the third who do its ordering was worse, roughly halved in two seasons
of three. **A population that is mostly one outcome will let an ordering clause pass on the
outcome nobody needs ordered.** This population has the same shape: most goalkeeper and defender
rows in any gameweek are players who do not appear.

So both reading clauses below are read **on the appeared rows**, because those
are the rows a decision can act on, and the all-rows figures are reported beside them so the
shape of the population stays visible. That choice is made here, before the numbers, and it makes
this gate harder to pass than `opening_two_part`'s, deliberately.

### The columns, all of them named

The out-of-fold table `phase_c_component_oof_v1` is the input, and every column the gate touches
is named here because the one that is not named is the one a runner picks once the data is in
front of it.

- **An appeared row** is `appearance_target == 1`. The table also carries `minutes_target`, so
  the column is named rather than left to a reader.
- **The outcome** is `realized_points = points_target.where(appearance_target == 1, 0.0)`, which
  is the convention `src/squadopt/evaluation/component_metrics.py` uses. This matters more than
  it looks: `points_target` is **NaN on every non-appeared row** by contract, and I checked it on
  the table rather than trusting the contract, finding it null on all 20,965 non-appeared
  goalkeeper and defender rows in scope. A runner that read `points_target` on the all-rows floor
  would drop two thirds of the rows and the floor would silently become a second appeared-rows
  clause, which is the one thing it exists not to be.
- **The comparator** is `control_expected_points`, the shipped composition as that table records
  it, and not a recomputation of it.
- **Rows whose composition route is `direct_control`** are dropped, and the record states how
  many. They carry no `appearance_probability` and no `expected_minutes_if_appearance` by
  contract (`component_metrics.py` requires those to be missing there), so both the candidate and
  its comparator are undefined on them, and `NaN >= 60` would quietly make `long` zero without
  anybody choosing it. There are **219** of them among the 33,235 goalkeeper and defender rows in
  scope, and the sibling audit drops them the same way and says so.
- **A row whose gameweek gives its club more than one fixture** (`fixture_count > 1`) is dropped
  and counted. The structure prices one match, and pricing a double gameweek as a single one
  would understate it for reasons that have nothing to do with the candidate.

### The population, in numbers I measured rather than assumed

Counted on the regenerated table: the three judged seasons hold **110** decisions, **104** of
them from target gameweek 4, carrying **33,235** goalkeeper and defender rows of which **12,270**
appeared. An earlier draft of this document said 147 folds, which is the four-season
all-gameweek set and not this population.

**1. Accuracy, with a floor on the whole population.** Mean absolute error against the shipped
composition:

- **Binding, on appeared rows:** pooled improvement with the 90 per cent interval's lower bound
  above zero, and an improvement in **every** judged season.
- **Floor, over all goalkeeper and defender rows in scope:** the pooled mean absolute error
  must **not be worse** than the shipped composition's. Not an improvement, a floor, and an
  exact tie passes: the clause is that the candidate may not be worse, so equality is not a
  failure. The floor reads the outcome through the convention named above, so the non-appeared
  rows are in it at zero rather than dropped as nulls.

**Pooled** means over all the judged seasons' rows together for an error, and the mean of the
judged seasons' own correlations for a rank, because a correlation pooled across seasons would
rank players from different seasons against each other. The two are different operations and the
document says which each clause takes.

The interval is a **paired block bootstrap over decisions**, 2,000 resamples, seed 0, block
length 4. The unit is the decision and not the row: players inside one gameweek share fixtures,
and this repository has both conventions live with about an order of magnitude between their
widths, so leaving it unstated would leave the width to be chosen once it is visible.

**2. Ordering, on appeared rows.** Within-position Spearman, separately for GK and for DEF, must
not fall below the shipped composition's by more than **0.010** in any judged season nor pooled.
The tolerance is the one `opening_two_part_prereg` fixed and is carried unchanged so the two are
comparable; it is not re-derived here and it will not be moved.

**3. Decision.** The **104** decisions named above and the harness
`prepare_phase_c_component_folds` uses, with the goalkeeper and defender rows' expected points
replaced by the candidate's and every other row left exactly as the table has it, scored against
the unmodified table with the official autosub and vice-captain policy. Mean realized difference
**at least zero** with **at most one** of the **three** judged seasons losing, paired by
decision, with a 90 per cent
season-aware moving block interval (2,000 resamples, seed 0, block length 4) reported beside it.
Both arms solve under `measurement_optimization_config()` and the record carries each solve's
status, because a proof and an incumbent are different evidence.

### Why there is a floor, and what it costs

Restricting the binding clauses to appeared rows closes the failure `opening_two_part` walked
into and opens its inverse: the product prices **every** goalkeeper and defender row, not only
the ones that appeared, so a candidate that is better on the appeared rows and worse over the
whole population would pass a clause that only looks at the former. "Reported beside it" is not
a defence, because nothing can be added once this document merges.

The floor is the answer, and it is deliberately weaker than the binding clause. Requiring an
improvement over all rows would re-admit the thing being avoided, since those rows are mostly
players who did not appear and predicting near zero for them is what a candidate can win on
without helping a decision. Requiring only that it is **not worse** says the candidate may not
pay for its gains with the rest of the population.

## Reported, not gated

- Calibration of the recalibrated clean-sheet probability on the judged seasons, by decile,
  predicted against realized.
- The candidate's error split by whether the clean sheet happened, which is where a structural
  model can be wrong in a way a rate model cannot.
- Goalkeepers and defenders separately throughout, because the two records that motivate this
  point at goalkeepers specifically and a pooled pass could hide a defender-side loss.
- Row counts entering each part, and the count of rows whose club has no rating that gameweek.

## The drop rule

A failure publishes the verdict as produced. The shipped composition stays exactly as it is, the
bar is not moved, and there is no small-fix exception: a changed candidate is a new candidate with
a new declaration. If the gate passes, that makes it eligible for the locked-holdout protocol and
nothing more, and whether to spend `2025-26` is a three-owner decision that this document does not
pre-empt.

A pass here is also **not** a proposal to change `prediction/`. That zone is İbo's, the change
would be proposed on #621 with this record behind it, and nothing is written there on the strength
of a development-fold result alone.

## The record

`docs/positional_defence.json` with its markdown twin and a row in `measurements_index.md`,
written by `scripts/measure_positional_defence.py`, which refuses to overwrite its record because
a gate is read once, refuses the locked holdout before anything is read, and names the seasons it
loaded in its own provenance.
