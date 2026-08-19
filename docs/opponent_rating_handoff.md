# Opponent strength and the rate model — a handoff to the prediction side

## Why this is addressed to you

Three measurements (`schedule_signal_study`, `team_rating_study`, `opponent_projection_study`)
end at the same place: opponent strength carries real information, and **there is no way to
spend it from outside `prediction/`**. Every remaining route runs through the rate model or
the features it reads, which is your zone. This document hands over what was measured, what
the mechanism is, the two decisions only you can make, and the smallest experiments that
would settle them. Nothing here proposes a change to your code — it proposes a question and
supplies the instrument.

Everything referenced is measurement-only, on development seasons. The 2025-26 holdout was
refused by configuration in all three studies.

## What was measured

**1. Opponent difficulty is real and small, and the calendar is the big half.**
Over 4,403 paired five-week windows, knowing how many fixtures a window holds is worth
+0.114 mean absolute error [+0.078, +0.151] and **+14.7 realized points per window**. Adding
difficulty on top of that is worth +0.026 [+0.007, +0.044] in error and **−2.6 points per
window** at the decision level. Error and decisions disagreed, and the decision is the one
that matters.

**2. A goal model beats the platform's rating at ranking players.**
A Dixon-Coles attack/defence rating fitted to archive goals — time-decayed, refitted at every
judged gameweek, half life and ridge selected per season on earlier seasons only — beats a
constant-rate baseline at predicting scorelines (+0.1020 log-likelihood per fixture
[+0.0756, +0.1323], every season), and orders attackers' points **three times** as well as
the published difficulty rating (+0.0631 against +0.0213), and defenders' better
(+0.0674 against +0.0473). It failed its own gate only on clean-sheet calibration
consistency, and its calibration breaks above 0.5 — where a defender is actually bought.

**3. Layering that rating onto the shipped projection loses points.**
On 110 walk-forward folds of the operational control, a multiplicative adjustment (attackers
by expected goals, goalkeepers and defenders by clean-sheet probability, both per fixture)
improved error by +0.0016 and cost **−0.91 realized points per gameweek** [−1.91, +0.16].

## The mechanism, which is the whole point of this document

The fitted coefficients say exactly what went wrong:

| Position | Fitted slope on the opponent signal |
| --- | ---: |
| GK | **+0.262** |
| DEF | **+0.228** |
| MID | **−0.041** |
| FWD | **−0.042** |

For the defensive half the sign is what anyone would predict. For the attacking half it is
**negative**: conditional on the control's projection, a player whose club the rating expects
to outscore its opponent *under*-performs that projection.

That is not a paradox, it is double counting. `baseline_expected_points` is
`points_per_90 × expected_minutes / 90`, and `points_per_90` is a shifted rolling feature —
a player at a strong, in-form club carries a high rate into the fixture *because his club has
been scoring*. The rating's expected-goals term is largely the same information arriving a
second time. Once the projection has been conditioned on, what remains of the signal is the
shrinkage of an over-extrapolated rate, and it points the other way.

There is a structural reason this cannot be fixed from outside: **a multiplier applied after
the fact cannot adjust the coefficient on form.** It is forced to accept the rate model's
weight on rolling form as given and can only add a correction on top. A jointly fitted model
can shrink the form coefficient to make room for the opponent term. That is the difference
between what was measured and what is being proposed, and it is the reason this is worth your
time rather than a closed question.

## Decision 1 — is the archive's `fixture_difficulty` admissible? (urgent, and yours)

While measuring the above, the published-difficulty variant of the same adjustment **passed
all three gate clauses**: +0.0121 error [+0.0100, +0.0143], +1.74 realized points per
gameweek [+0.52, +3.03], positive in every judged season — on the order of **+64 points a
season**, the largest single effect this programme has measured outside the chips.

It is not being carried forward, because of this:

The archive stores exactly one difficulty value per club, per venue, per season — verified
constant across 2021-22 … 2024-25, so no fixture-level hindsight is possible. Season-level
hindsight is testable: a rating written before a season should track the **previous** season's
table more closely than the coming one's.

| Season | Correlation with this season's table | With the previous season's |
| --- | ---: | ---: |
| 2022-23 | +0.731 | +0.850 |
| 2023-24 | +0.894 | +0.845 |
| **2024-25** | **+0.940** | **+0.372** |

2022-23 behaves like a pre-season rating. 2023-24 is marginal. 2024-25 is not defensible —
and it is also the season with the largest error improvement of the three (+0.0192 against
+0.0085 and +0.0086), which is the pattern contamination produces.

`features/fixtures.py` attaches `mean_fixture_difficulty` and `minimum_fixture_difficulty`
unshifted, on the stated ground that the fixture list and its difficulty are published before
the deadline. **That reasoning is correct for the live platform and not obviously correct for
the archive**, whose single snapshot may have been taken at any point in the season.

What we need from you, in order of value:

1. **Rule on the column.** Is the archived value pre-season, or is it whatever the platform
   held when the snapshot was taken? If the latter, the column is not a pre-match feature on
   development seasons, whatever it is on live ones.
2. **Say what it invalidates.** The fixture *count* is unaffected — a calendar cannot be
   contaminated this way, and the count is where the measured +58/season lives. But any result
   that leaned on `fixture_difficulty` deserves a second look, and you are the one who knows
   which those are.
3. **If a genuinely pre-season capture is obtainable, that is worth more than anything in the
   three studies.** The live path now takes one before each season; the archive does not
   provide one for earlier seasons. A pre-season snapshot that reproduces even part of that
   +1.74 per gameweek would be the largest available win, and it needs no model at all.

### Direct evidence, added 2026-08-19

The correlation argument above is circumstantial. This is not. A live capture taken
2026-08-16, five days before the 2026-27 season's first kickoff, publishes **fixture
difficulty for all 380 fixtures** — and publishes almost no **team strength**:

| Source | `strength` | `strength_overall_home` | `strength_attack_home` |
| --- | --- | --- | --- |
| Live capture, 2026-08-16 (pre-season) | null | **4** (a 1–5 scale) | **0** |
| Archive `2026-27/teams.csv` today | null | 4 | 0 |
| Archive `2024-25/teams.csv` (finished) | 5 | **1350** | **1390** |
| Archive `2023-24/teams.csv` (finished) | 5 | 1350 | 1370 |

Before a season the platform fills only a coarse one-to-five overall rating and leaves attack
and defence at zero for all twenty clubs. A finished season's archive carries those same
fields populated on a thousand-point scale. **The archive's team-strength columns are
therefore demonstrably not pre-season values** — whatever moment they describe, it is not
August.

That settles the strength columns outright. It does not settle `fixture_difficulty`, which
*is* published pre-season and so could legitimately be a pre-match feature; whether the
archived copy equals the pre-season one is the open question, and it is now being measured
rather than argued. `docs/preseason_difficulty_prereg.md` records the capture, the
comparison and the thresholds, all fixed before the season started.

This is filed as a data-contract question rather than a patch on purpose: `data/` and
`features/` are yours, and a silent shift of that column would change every recorded
measurement that read it.

## Decision 2 — does opponent strength enter the rate model, and how?

Three routes, cheapest first. They are not alternatives to each other in the long run, but
each is a separate declared candidate and each answers a different question.

### Route A — an opponent column in the learned rate (about a day)

`fit_learned_rate` is a minutes-weighted ridge whose declared inputs are

```python
rate_input_columns(window) == (
    per_90_feature_name(window),
    rolling_feature_name("appeared", window),
    minutes_per_appearance_feature_name(window),
    "fixture_count",
    "home_fixture_count",
)
```

The calendar is already in there. Adding one or two opponent columns — the rating's expected
goals for the player's club, and the clean-sheet probability it implies — is a change to that
tuple, a bump of `LEARNED_RATE_FEATURE_CONTRACT_VERSION`, and nothing else.

**The question it answers:** does joint fitting recover what layering lost? If the ridge is
allowed to shrink the coefficient on rolling form, does the opponent coefficient come out
positive for attackers? That is the single most informative cheap experiment available, and
it is a one-line change to a declared list.

Suggested pre-registration, so the answer is not negotiated afterwards: the candidate is
compared to the current learned rate on the frozen 147-fold objective, and it must improve
**realized squad points**, not only prediction metrics. The layering study is the standing
proof that those two can disagree.

### Route B — decontaminate the form feature itself (two to three days)

The deeper fix, and the one that addresses the mechanism directly. The rolling form feature
currently measures "points per 90 earned, against whoever happened to be played". Divide each
past gameweek's points by the difficulty multiplier of the fixture it was earned against
*before* rolling, and the feature measures the player rather than his schedule. Then the
upcoming fixture's multiplier is applied once, at projection time, with nothing to double
count.

This is the textbook shape and it is also the more expensive change: it moves
`FEATURE_GENERATION_CONTRACT_VERSION` (`form_window_v1`), which every recorded measurement's
provenance names. Worth doing only if Route A says the joint signal is there.

A cheap diagnostic that costs an afternoon and would tell you whether Route B is worth
planning: correlate a player's rolling form with the average strength of the opponents that
form was earned against. If that correlation is near zero, the contamination is small and
Route B is not the bottleneck. If it is substantial, Route B is where the increment lives.

### Route C — a positional structure for goalkeepers and defenders (measurement first)

A defender's points are not a smooth function of anything. They are an appearance point, plus
four for a clean sheet, plus bonus, plus the new defensive-contribution points in the
2026-27 rules. Multiplying a rate by an ease factor models none of that.

The rating already emits the right object: `TeamRating.clean_sheet_probability(...)` returns a
probability, not a scale. A two-part projection for GK and DEF — `P(plays) × (appearance +
4 × P(clean sheet) + expected bonus)` — is a different model, not an adjustment, and it is the
one place where a goal model has something a form model structurally cannot produce.

**Two warnings before you build it.** The rating's clean-sheet calibration is good through the
middle bands and breaks at the top: over the 40 judged fixtures where it promised better than
an even chance, the clean sheet happened a third of the time (predicted 0.534, realized
0.325). It needs a cap or a recalibration at the top of the distribution before it is allowed
to price a defender. And 2026-27 changes what a defender is paid for — the defensive-
contribution rule means clean sheets are a smaller share of a defender's points than they were
in the seasons this was measured on.

## What is ready for you to use

`squadopt.experiments.team_rating` is measurement-layer code, deliberately not in `features/`,
because promoting it is your call and not mine. It is importable as it stands:

```python
from squadopt.experiments.team_rating import (
    load_match_results,  # archive fixtures with scorelines, keyed by club code
    promoted_clubs,  # per season, clubs absent from the season before
    measure_promoted_prior,  # what a promoted club's rating looks like, measured
    select_dixon_coles_config,  # half life and ridge, chosen on earlier seasons only
    fit_dixon_coles,  # one rating, fitted on matches before an `as_of`
)

rating = fit_dixon_coles(
    matches, as_of=deadline, config=chosen, promoted_prior=prior, newly_promoted=arrivals
)
home_goals, away_goals = rating.expected_goals(home_club, away_club)
clean = rating.clean_sheet_probability(club, opponent, is_home=True)
```

Three properties that matter for your cost model:

- **A fit takes about ten milliseconds.** The parameter block has an exact analytic gradient
  and only the one-dimensional low-score correction is a grid search. Refitting at every one
  of 147 folds is seconds, not minutes — unlike the learned candidate's 590 s recorded in
  `candidate_runtime`.
- **It cannot leak.** It reads only matches that had already kicked off at its `as_of`, and a
  unit test poisons every later match and asserts the fit does not move. Whatever you conclude
  about `fixture_difficulty`, this instrument is not exposed to that doubt.
- **It handles promoted clubs honestly.** A club with no top-flight matches is given the
  measured average of clubs promoted in earlier seasons, applied as the mean its ridge pulls
  toward, so it also governs how a promoted club is rated three matches into a season.

Artifacts, each with its note recording what it does and does not settle:
`docs/schedule_signal_study.md`, `docs/team_rating_study.md`,
`docs/opponent_projection_study.md`.

## Protocol, if you take a route

Unchanged from `candidate_gate_spec.md`, and repeated here so nothing has to be rediscovered:

1. A `CandidateDeclaration` written and fingerprinted **before** the run, naming
   `changed_component`, the exact input list, and everything frozen around it.
2. `run_declared_candidate_benchmark` once, on the 147 development folds, against the
   deterministic control and the Ridge reference in one process.
3. The objective is `single_gameweek_realized_squad_points_v1`. **Please do not accept a
   prediction-metric improvement as the result** — this programme has now measured two cases
   where error improved and realized points fell.
4. A passing development verdict is eligibility for the locked-holdout protocol, never
   automatic promotion.
5. Anything reaching the live path needs the gameweek-one replay to stay byte-identical
   (`scripts.recommend_current_squad --snapshot-id <id>`, per `opening_week_runbook.md`).

## Honest expectations, and when to stop

- The measured levers so far are **chips (+100/season)** and **fixture calendar knowledge
  (+58/season)**. Opponent difficulty is plausibly a fraction of that, because most of it is
  already priced into form and price. Every stage measures an **increment**, never a total.
- The one large number measured here — +1.74 points per gameweek from the published rating —
  is the number most likely to be contamination. Treat it as the motivation for Decision 1,
  not as a target.
- **A reasonable stop condition:** if Route A's opponent coefficient comes out negative or
  indistinguishable from zero for attackers under joint fitting, the attacking side is done —
  form already carries it — and only Route C (the defensive structure) is worth continuing.
  That would be a clean, publishable negative and it costs one day to find out.

## What not to do

Do not apply a difficulty multiplier on top of the existing projection. That is the exact
thing that was measured, and it costs about a point a gameweek. If opponent strength enters,
it enters where the rate is estimated.

## What the optimisation side will do for you

- Run any candidate you declare through the frozen 147-fold decision objective and report
  realized squad points with the fold-level interval, not only error.
- Supply the rating at any `as_of` you name, in whatever shape your features want.
- Re-run the hindsight check on any new capture you obtain, so a pre-season snapshot can be
  cleared or rejected on evidence before it is built on.
