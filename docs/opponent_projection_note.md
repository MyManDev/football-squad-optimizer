# The stage that inverted the expectation, and the finding that outranks it

`opponent_projection_study.md` was written to answer one question — does a better ordering of
fixtures become better decisions — and it answered a different, more important one on the
way. This note separates the two, because the headline result cannot be used and the
incidental result affects code outside this study.

## What was expected, and what happened

Stage one found that scaling a projection by the platform's published difficulty rating
improved error slightly and lost points at the decision level. Stage two found that a
Dixon-Coles rating fitted to goals orders attackers' points three times as well as the
published rating does. The obvious prediction was that the rating would succeed inside a
projection where the published rating had failed.

The opposite happened, on 110 walk-forward folds of the operational control:

| Candidate | Error | Ordering | Decision (points per fold) | Gate |
| --- | ---: | ---: | ---: | --- |
| `R_team_rating` | +0.0016 [+0.0011, +0.0021] | −0.0003 | **−0.91** [−1.91, +0.16] | fails |
| `P_published_rating` | +0.0121 [+0.0100, +0.0143] | +0.0021 | **+1.74** [+0.52, +3.03] | passes |

The published rating passed all three declared clauses, including the strict decision clause,
and did so in every judged season (+1.11 / +2.22 / +1.87). At roughly 37 folds a season that
is on the order of **+64 points a season** — the largest single effect this programme has
measured outside the chips.

## Why the fitted rating loses

The coefficients say it plainly. For goalkeepers and defenders the rating's slope is positive
and large (+0.262, +0.228): a clean-sheet probability above average lifts the projection, and
that is the direction anyone would predict. For midfielders and forwards the fitted slope is
**negative** (−0.041, −0.042). Conditional on the control's own projection, a player whose
club the rating expects to score more than usual *under*-performs that projection.

That is not a paradox, it is double counting. The control's projection is built from a
player's own rolling form, and a player at a strong, in-form club carries a high rate into
the fixture precisely because his club has been scoring. The rating's expected-goals signal
is largely the same information arriving a second time, so once the projection has been
conditioned on, what is left of the signal points the other way — the familiar shrinkage of
an over-extrapolated rate. The published rating, being a coarse season-constant integer,
overlaps far less with recent form, so it carries an increment the projection does not
already hold.

The multipliers confirm how gentle both adjustments are: mean 0.996 for the rating (range
0.74–1.12) against 0.990 for the published rating (range 0.60–1.31). The published version
moves projections nearly twice as far and changes two starters per fold against one.

## The finding that outranks the headline: the published rating is not admissible

The published rating passed its gate, and it is **not being carried forward**, because the
signal it uses fails a leakage check that was run as part of the study.

The archive stores exactly one difficulty value per club, per venue, per season — verified
constant across all four development seasons — so it cannot encode fixture-level hindsight.
Season-level hindsight is a different question and it is testable: a rating set before a
season should track the *previous* season's table more closely than the coming one's.

| Season | Correlation with this season's table | With the previous season's |
| --- | ---: | ---: |
| 2022-23 | +0.731 | +0.850 |
| 2023-24 | +0.894 | +0.845 |
| 2024-25 | **+0.940** | **+0.372** |

2022-23 behaves like a pre-season rating. 2023-24 is marginal. **2024-25 is not defensible**:
the archived rating tracks the season it describes almost perfectly and barely tracks the
season before it, which is the signature of a value written down after the fact. It is also
the season with the largest error improvement of the three (+0.0192 against +0.0085 and
+0.0086), which is exactly the pattern contamination produces.

So the honest reading is: **the gate result stands as computed, and the evidence is
inadmissible.** The bar was not moved and the verdict was not rewritten; a passing candidate
is simply not carried forward when its input was not knowable at the deadline it is used at.

### This reaches beyond this study

`features/fixtures.py` attaches `mean_fixture_difficulty` and `minimum_fixture_difficulty` to
every player-gameweek row, unshifted, on the stated ground that the fixture list and its
difficulty are published before the deadline. That reasoning is correct for the live
platform, where the rating really is published in advance. It is not obviously correct for
the *archive*, whose single per-season snapshot may have been taken at any point — and the
2024-25 numbers say at least one of them was taken late.

This does not invalidate the measurements that used those columns: the strongest measured
fixture effect in this repository is the fixture **count**, not the difficulty, and the
calendar cannot be contaminated this way. But every result that leaned on
`fixture_difficulty` deserves a second look, and this belongs to the data side. It should go
to İbrahim as a data-contract question, not be fixed here.

The fitted rating carries no such doubt: it is refitted at every judged gameweek on matches
that had already kicked off, and it is structurally incapable of this failure. That is worth
something even though it lost.

## What this changes about the programme

- **Stage three's own question is answered, and the answer is no.** A goal-model adjustment
  layered on top of the operational control does not improve decisions; it costs about a
  point a gameweek. Anything further in this direction has to stop layering and start
  *replacing* — the rating belongs inside the rate model, where it would not be double
  counting, and that is `prediction/`, which is the data side's to change.
- **The real opportunity is a clean pre-season fixture signal.** The published rating's
  measured effect is large, and if a genuinely pre-season snapshot reproduces even part of it,
  it is worth more than anything in stages one and two. That needs a capture taken before a
  season starts, which the live path now produces for 2026-27 and the archive does not
  provide for earlier ones.
- **Stage four is unaffected.** Multi-week scenario paths, rivals, and chip timing under a
  rank objective do not depend on this stage passing; they depend on the weeks differing,
  which the calendar already delivers.

## Limits

- **One shape only.** A multiplicative adjustment on a fitted control is the simplest way to
  add opponent information and the easiest to double-count with. A jointly fitted rate model
  would not have this problem and is not tested here.
- **Single gameweeks.** Folds are one gameweek each, so this says nothing about a five-week
  window; stage one covered that and disagreed with this result on the published rating's
  sign. The two setups differ in projection, horizon and squad construction, and neither is a
  refutation of the other.
- **Fresh squads.** Every fold builds a fifteen from the whole pool under the full budget,
  identically for both arms. It compares projections fairly; it does not describe a season.
- **110 folds, three seasons.** The decision interval is wide (±1.2 points on the published
  arm) and the fold is the resampling unit, which is the right unit and a small one.
