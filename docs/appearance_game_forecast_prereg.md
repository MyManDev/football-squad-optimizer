# The game's forecast as a who-plays input on live gameweeks: protocol

Status: draft, written on 2026-10-14 for step 1 of #1004. It binds from the moment it merges.
On the date it was written no candidate outcome had been computed on any gameweek, and no
reading under this protocol had been taken. The newest deadline the repository's fixture
table shows still open is gameweek 7 of 2026-27, 2026-10-17T10:00:00Z
(`web/public/data/fixtures.json`). This document changes no forecast, model, default, copy or
live control, and it promotes nothing.

If it merges before the gameweek 7 deadline, gameweek 7 is the first gameweek it scores. If
it merges later, the first scored gameweek is the first one whose deadline falls after the
merge. A late merge can never admit a week whose matches could already have been seen.

The four undecided points of #1004, and the three method details its second comment raised, were
decided by the owner on 2026-10-14, before this pull request opened (the decision comment on
#1004, issuecomment-6169172503): every default stands as proposed. Each is marked `(default N of
#1004, accepted 2026-10-14)` where it applies. After the merge nothing in this document moves.

## Why this is written

Members' plans put points on players who then do not play. Gameweeks 4 and 5 of 2026-27 are
the two live weeks with both a pre-deadline capture and a yardstick. Over all players, our
decided forecast's error was lower than the game's own `ep_next` in both weeks, MAE 1.194
against 1.234 and 1.120 against 1.163 (`docs/live_projection_audit.md:87`, `:89`, `:136`,
`:138`), and over each forecast's own top 40 per position, where the solver buys, lower again,
2.349 against 2.824 and 2.163 against 2.569 (the same lines). But 15.5 and 15.3 per cent of
our decided points sat on players who did not appear, against 11.4 and 10.8 per cent of the
game's (the same lines, last column). Reading 6 of the audit says on whom: the players our
availability rule had named carried 9.8 and 9.7 of our points against 11.9 and 10.3 of the
game's, and the players nobody had named carried 121.0 and 115.4 against 93.4 and 85.6
(`docs/live_projection_audit.md:106-107`, `:155-156`). The gap is not in the availability
rule. It sits on players nobody flagged, which no flag repairs.

`ep_next` is in every capture and is read today by one function, as a yardstick
(`game_forecast`, `src/squadopt/data/sources/fpl_live.py:2353`), whose docstring says it is
"never an input" (`:2361-2363`). The archive cannot test it: its `xP` was collected after
the match (`docs/data_pipeline.md:396-398`). So live weeks are the only test, and a live week
read without a frozen rule is spent. The audit itself claims nothing before six pooled
gameweeks and says a finding becomes a candidate under its own protocol
(`docs/live_projection_audit_prereg.md:87-89`, `:93`). This document is that protocol. It
measures both directions: adding the game's forecast can cost points where our ordering is
better, as well as win them where our appearance side is worse.

## What has already been read, and is spent

- **Gameweeks 1 to 5 of 2026-27.** Gameweek 1 was read by the audit for our decided numbers
  only; gameweeks 2 and 3 have no pre-deadline capture (`docs/live_projection_audit.md:8`,
  `:177-180`); gameweeks 4 and 5 are the audit's two full readings, and the figures above
  come from them. None of the five is scored here. No candidate outcome is computed on any
  of them, gameweeks 4 and 5 included: the blend's error on those weeks is never read.
- **Every week whose deadline falls before the merge.** Gameweek 6 (deadline
  2026-10-10T10:00:00Z) is already played at writing and is spent. If the merge slips past
  2026-10-17T10:00:00Z, gameweek 7 is spent too, and so on. A spent week is listed in the
  record as spent, never scored.
- **The development seasons** are not read. This candidate has no archive test, and #1004
  excludes any archive measurement and any read of 2025-26. The football protocol's
  development variance (`research/football_candidate_development_record.json`) is not cited
  here for the same reason; the second comment on #1004 records why.

## Which capture a gameweek is scored from

The scored capture is the capture the week's published league decision read: the
`snapshot_id` the ledger's `decision.json` names for that gameweek
(`src/squadopt/live/ledger.py:358`), which is the capture the league pages of that week
were built from. Its own target must be the gameweek:
`read_inputs(snapshot, season=..., gameweek=None).deadline.gameweek`
(`src/squadopt/live/recommendation.py:434`), the earliest deadline the capture's own
bootstrap shows still open at its capture instant. A capture taken before the deadline but
targeting an earlier gameweek is that earlier gameweek's, and nobody could have had this
gameweek's advice from it (`advise_entry`, `src/squadopt/application/advice.py:1073`,
refuses a request for any gameweek other than the capture's own; `DeadlinePassedError`,
`src/squadopt/platform/advice_submit.py:86`).

The control handoff is the one the backend pairs with that capture (`load_capture_identity`,
`src/squadopt/platform/capture_context.py:176`), and the ledger's
`metadata.projection_handoff_fingerprint` must name it, as the audit's runner checks
(`scripts/measure_live_projection_audit.py:116-119`, `:218`). Both arms are read from the
scored capture and no other: not an earlier capture of the same gameweek, and never a capture
whose own target is another gameweek. A week with no published league decision is missing.

The settled outcome is read from a later capture that marks the gameweek scored
(`scored_gameweeks`, `src/squadopt/data/sources/fpl_live.py:1764`: `finished` and
`data_checked` both true) and holds its live payload (`live_event_outcomes`, `:1303`).

## The two arms, down to the column

Both arms are one number per player of the scored capture's roster, keyed on the FPL `code`,
which is what `player_snapshot` (`src/squadopt/data/sources/fpl_live.py:842`) carries as
`player_id` and what `live_event_outcomes` keys the outcome on (`:1304`). The join to the
outcome is on that `code`, as the audit joins (`audit_frame`,
`src/squadopt/evaluation/live_projection_audit.py:118-120`, an inner join: a roster player
the outcome does not name is left out and counted, never scored as zero).

- **Control, `ours_decided`.** The handoff's `expected_points` times the same capture's
  availability multiplier, exactly as the audit defines it
  (`src/squadopt/evaluation/live_projection_audit.py:11-12`, `:131`). The multiplier is the
  availability rule's own (`apply_availability`, `src/squadopt/prediction/availability.py:131`;
  a stated `chance_of_playing` before the status, `:139-142`; the product clipped at zero,
  `:189`), and it is what the in-season handoff route applies to the handoff before the
  solver reads it (`src/squadopt/live/recommendation.py:602`). So the control is what the
  solver read, to the number. A player the rule does not name is unchanged (`:131` of the
  audit module, `fillna(1.0)`).
- **Candidate, `blend`.** `blend = 0.5 * ours_decided + 0.5 * ep_next`, per player, with
  `ep_next` read from the same capture's bootstrap by `game_forecast`
  (`src/squadopt/data/sources/fpl_live.py:2353`). Where the capture has no `ep_next` for a
  player, because the field is null or unparseable and `game_forecast` leaves him out
  (`:2365-2368`, `:2377-2385`), `blend = ours_decided`. Absent is not zero. Nothing is fitted
  and there is no threshold: the weight is 0.5 for every player, every position, every price
  and every week. `(default 2 of #1004, accepted 2026-10-14)`
- **Every difference is candidate minus control**, in every reading and every table, and
  the record pins the sign.

Blank and double gameweeks enter as the audit enters them. The outcome row is the game's own
total for the gameweek: `stats.minutes` and `stats.total_points` of the live payload
(`src/squadopt/data/sources/fpl_live.py:1355`, `:1367`), summed by the game over however many
fixtures the player's club had. A player whose club has no fixture appears with zero minutes
and zero points against whatever each arm forecast him, which both arms read from a capture
that already knew the blank; a player with two fixtures appears with both fixtures' minutes
and points against a forecast that was made for the whole gameweek, ours and the game's
alike. No row is dropped and nothing is divided. The audit's protocol says the same of its
prior-minutes divisor (`docs/live_projection_audit_prereg.md:74-75`); here no divisor is
involved.

The control's handoff version is whatever was served that week. On 2026-09-25 it was
`phase_c_control_components_v1` (`docs/live_projection_audit.md:132`). If a later week's
handoff is another version (#531 may change it before reading 1), that week is scored with
the version that was served, and the record names every week's version and reports each
version's weeks separately beside the pooled figure. A change to the control's producer that
moves its forecasts without a new version name is named in the record if it is found.

## Missing weeks

Every gameweek from the first scored one to the reading's last appears in the record. A
gameweek is missing when any of the following holds, and the record lists it with its reason:

- the ledger holds no published league decision for it: no `decision.json`, or one the ledger
  holds as a roll rather than a published decision (`ROLL_MODE`,
  `src/squadopt/live/ledger.py:611`);
- the capture the decision names does not target the gameweek. The last capture before its
  deadline then targets an earlier gameweek, and the week is not scored from it: that
  capture's handoff is the earlier gameweek's, and the backend took no new advice work from
  it once that gameweek's deadline had passed (`DeadlinePassedError`,
  `src/squadopt/platform/advice_submit.py:86`);
- the backend cannot pair the scored capture with exactly one handoff, or the handoff the
  ledger names is not among the handoffs kept for that capture;
- the scored capture's bootstrap has no `ep_next` field at all, so `game_forecast` refuses it
  (`_require_fields`, `src/squadopt/data/sources/fpl_live.py:2372`). A capture where the
  field is present but null for some players is not missing; those players are blended at
  the control, as defined above, and their number is reported;
- no later capture both marks the gameweek scored (`scored_gameweeks`,
  `src/squadopt/data/sources/fpl_live.py:1764`) and holds its live payload;
- for reading 3 only: the scored capture holds no squad for any member of league 352490.
  Readings 1, 2 and 4 are still taken for such a week.

A missing week is not repaired. It is never filled with another capture's handoff, with a
forecast rebuilt after the deadline, or with an `ep_next` read from a later capture. A
projection written after the deadline from a pre-deadline capture is labelled `replay`
wherever it is shown and is never pooled, as the audit's protocol requires
(`docs/live_projection_audit_prereg.md:39-40`). The owner's weekly runs are what keep weeks
from going missing: each scored week's decision capture, its handoff and a later settled
capture stay on disk through gameweek 20 (#1004, "Depends on").

## Populations

Every reading is taken over one or more of three populations, built per gameweek on the
joined rows:

- **all players**: every roster player of the scored capture with an outcome row;
- **the decision population**: the union of each arm's top 40 per position by its own
  forecast, `TOP_PER_POSITION` (`src/squadopt/evaluation/live_projection_audit.py:34`,
  ranked as `_top` ranks, `:188-192`), with both arms scored on the same rows. The audit's
  own paired difference ranks by one forecast only (`paired_difference`, `:359`); the union
  is this protocol's population and its runner builds it;
- **the players who appeared**: minutes above zero (`appearance`,
  `src/squadopt/data/sources/fpl_live.py:1364`).

A player an arm does not name is left out of that arm's numbers and counted. Under the
definitions above both arms name the same players, so the two arms always rest on the same
rows and the counts are reported to show it.

## Reading 1, accuracy

**Unit.** One player in one scored gameweek.

**Statistics.** For each arm, over each of the three populations: the mean absolute error
and the bias (realized minus forecast), as `_error_block` computes them
(`src/squadopt/evaluation/live_projection_audit.py:144-155`). Per gameweek, and pooled as
equal-gameweek means. The per-week difference in MAE, candidate minus control, on the
decision population is the series the ship rule's clause (a) and the stop rule's accuracy
interval read.

## Reading 2, ordering

**Unit.** One player in one scored gameweek, decision population only.

**Statistics.** For each arm and each position, the Spearman rank agreement between the
forecast and the realized points within the position in the gameweek, as `_rank_agreement`
computes it (`src/squadopt/evaluation/live_projection_audit.py:158-178`; a position with
fewer than three rows or no variation is undefined and reported as missing, never as zero).
Pooled over the scored gameweeks as that function pools, each gameweek-position group
weighted by its players. The gain is candidate minus control per position, and the pooled
gain averaged over positions gives the four positions equal weight, which is the ranking
gate's own convention (`docs/prediction_ranking_gate.md:15-20`). Clause (b) of the ship rule
reads the pooled gain per position and its unweighted mean.

## Reading 3, decisions

**Unit.** One member in one scored gameweek, for every member of league 352490 whose squad
the scored capture holds.

**Computation.** For each arm, `advise_entry` (`src/squadopt/application/advice.py:1073`)
computes the member's one-week `saf-puan` plan from the scored capture with that arm's
projection: strategy `COMPUTED_MODE` and window `COMPUTED_WINDOW`
(`src/squadopt/application/advice_capabilities.py:19-20`), no rival (`rival_entry_id` is
`None`, `advice.py:150`), Top 100 weight zero, the manager's word off and no chip, which is
the plain request (`switch_identity` defaults, `src/squadopt/platform/advice_switches.py:162-164`;
no chip is offered on the member path, `advice.py:561-563`). The candidate arm's projection
is the control's `Projection` with `expected_points` replaced by the blend after availability,
exactly where the ship step would apply it (`src/squadopt/live/recommendation.py:602`), and
nothing else about it differs: same roster, same prices, same availability diagnostics.

Both arms are solved under the same planner revision, named in the record as the
`planner_policy_id` (`member_planning_policy_v2`, `src/squadopt/live/transfers.py:213`) and
the `repository_commit` the advice record carries
(`src/squadopt/application/advice_record.py:679-685`), and under the same deterministic
budget: the one-week path's `PLAN_DETERMINISTIC_TIME_LIMIT`, 20.0 deterministic units
(`src/squadopt/planning/optimizer.py:89`, taken when the caller passes none, `:1365-1366`),
with `PLAN_WALL_CEILING_SECONDS`, 300.0 (`:90`), as a safety stop and never a budget. The
plans are computed at reading time from inputs that all precede the deadline.

**Scoring.** Both plans are scored on `RECORDED_ADVICE_SCORING_BASIS`
(`src/squadopt/application/weekly_suggestion_eval.py:290`): official automatic substitutions
and captaincy, minus the plan's transfer hit, on the gameweek's settled points. A pair in
which either plan is not scoring-complete, or the planner did not prove it, or the wall
ceiling rather than the deterministic budget stopped it, is left out and counted. A pair in
which both arms produce the same plan is counted, scored as a difference of zero, and
reported beside every mean, because such pairs may be most of them.

**Statistic.** `e = realized(candidate plan) - realized(control plan)` per pair. Reported: the
number of pairs, how many differ in decision, the mean of `e` over all pairs and over the
differing pairs, and wins, ties and losses. Each gameweek also gets one value, that week's
member mean over all its pairs, and that per-week series is what clause (c) of the ship rule
and the stop rule's decision interval read. The members share one projection, one set of
matches and overlapping squads, so the week is the unit
(`src/squadopt/evaluation/live_series.py:27-31` names this as the designated reuse).

## Reading 4, reported and not gated

For each arm, over all players: the forecast points carried by players who did not appear,
their share of the arm's total, and the split of audit reading 6, by position, by price
band, by the size of the forecast and by whether our availability rule had named the player
before the deadline (`absent_forecast`,
`src/squadopt/evaluation/live_projection_audit.py:256-316`; a player is named when his
decided forecast is below his unconditional one, `:274`). Both arms are read against the
same naming. This reading carries no verdict. It says whether the blend moved the points
that motivated the candidate, and it is reported per gameweek and pooled.

## Statistics

The gameweek is the unit of every interval. Each interval is
`season_aware_moving_block_interval` (`src/squadopt/evaluation/statistics.py:49`) on the
per-gameweek values, all keyed to season `2026-27`, with the `PromotionPolicy()` defaults
(`src/squadopt/evaluation/promotion.py:24-28`): a 90 per cent interval
(`confidence_level` 0.90), 5,000 resamples (`bootstrap_resamples`), blocks of four gameweeks
(`moving_block_length` 4) and seed 0 (`deterministic_seed`). `min_mean_improvement`, 0.5, is
part of the same defaults and is not a threshold of this protocol's ship rule; the ship rule
states its own. The candidate id handed to the resampler is
`appearance_game_forecast_blend-live-2026-27`. No interval is printed on fewer than six
scored gameweeks, in any reading. No interval is printed on players inside one gameweek,
because they share fixtures (`docs/live_projection_audit_prereg.md:90-92`). Every difference
is candidate minus control.

## What is expected, declared before looking

`squadopt.evaluation.live_series` states the minimum-detectable-effect formula
`(z_(1-alpha/2) + z_power) * sd / sqrt(n)` (`src/squadopt/evaluation/live_series.py:33-34`,
`detectable_effect`, `:209-227`). Here it is taken with the verdict's two-sided 90 per cent
interval, `z_0.95 = 1.6449`, and power 0.80, `z_0.80 = 0.8416`, so the multiplier is 2.4865.
`n` is 6 at reading 1 with an on-time merge (gameweeks 7 to 12) and 14 at reading 2
(gameweeks 7 to 20). No standard deviation below comes from a candidate outcome: each is
copied from a committed record, by file and field, and the arithmetic on it is shown. No
committed record holds a per-week series of this candidate's own contrast, so each clause
cites the closest one and says why it is only the closest.

**Clause (a), the per-week MAE difference on the decision population.** The closest committed
series is the audit's paired difference in absolute error, ours as decided minus the game's,
over the game's top 40 per position, in `docs/live_projection_audit.json`:
`gameweeks.4.projections[1].reading.ours_decided_minus_game.top_per_position_difference`,
the pre-deadline `phase-c-component-elite-top100-v1` handoff that decided gameweek 4,
-0.37251432298151205, and
`gameweeks.5.projections[0].reading.ours_decided_minus_game.top_per_position_difference`,
the live `phase_c_control_components_v1` handoff, -0.29326566628741924. The sample standard
deviation of the two is 0.0560. Then `2.4865 * 0.0560 / sqrt(6) = 0.0569` and
`2.4865 * 0.0560 / sqrt(14) = 0.0372` points of MAE per player. Two caveats are part of the
declaration: the series has two weeks, so its spread is barely estimated; and it is a
different contrast, ours against the game on the game's own top 40. Since the blend sits
halfway between the two, the blend's per-week MAE difference against the control is bounded
by half the ours-against-game difference in each week, so the spread above overstates the
blend's and the detectable effects are conservative.

**Clause (b), the pooled within-position Spearman gain.** The closest committed series is the
audit's per-week within-position rank agreement, player-weighted over positions, in the same
file: under `gameweeks.4.projections[1].reading`, the field
`forecasts.ours_decided.rank_agreement_within_position.weighted_mean`, 0.7026916260319205,
against `forecasts.game.rank_agreement_within_position.weighted_mean`, 0.7040468789127731;
and under `gameweeks.5.projections[0].reading`, the same two fields, 0.7387336622431652
against 0.7424469842897884. The game minus ours is +0.0014 and +0.0037, sample standard
deviation 0.00167. Then
`2.4865 * 0.00167 / sqrt(6) = 0.0017` and `2.4865 * 0.00167 / sqrt(14) = 0.0011`. Clause (b)
is a threshold on a pooled statistic rather than an interval, so this figure says only how
small a per-week shift the series could tell from noise; the clause's floor, no position
losing more than 0.01, is six times it at reading 1.

**Clause (c), the mean per-week member-plan difference.** No committed record holds per-week
member-plan differences between two projections; the live member-week instrument refuses to
produce one by design (`src/squadopt/evaluation/live_series.py:14-17`). The closest committed
standard deviation of a weekly squad-points difference between two systems is
`docs/measurement_instrument.json`, `precision.raw.standard_deviation`, 15.097098212213622,
over `precision.raw.folds`, 147 paired development decisions of 2021-22 to 2024-25 (free
squad selection, Phase C component base minus the historical ridge control). Then
`2.4865 * 15.0971 / sqrt(6) = 15.33` and `2.4865 * 15.0971 / sqrt(14) = 10.03` points a week.
The same record states its own two-sided effect at alpha 0.05 and power 0.80 over 147 folds,
`precision.raw.iid_mde_alpha_0_05_power_0_8`, 3.488499380776099, which the formula reproduces
(`2.8016 * 15.0971 / sqrt(147)`), so the arithmetic and the record agree. A member's two
one-week plans share his squad and differ by at most the transfers and the eleven, so their
weekly difference spreads far less than a free-squad contrast; the figures above are an upper
bound. Clause (c) is a direction floor, as the football protocol's reading two is, and is
not expected to separate from zero on 6 or 14 weeks.

Expectations:

- I expect clause (a) to hold, and by less than the 0.37 and 0.29 the game's forecast was
  behind ours on its own top 40, because the blend keeps half of our ordering.
- I expect clause (b) to be close to zero in both directions and undecided by the data.
- I expect clause (c) to rest mostly on identical pairs, and its per-week mean to be small
  and of either sign.
- The owner accepted the sources above on 2026-10-14 (the decision comment on #1004): the
  minimum detectable effects rest on the named committed records with their stated reasons
  and bounds, and the power report is not amended further.

## When it is read

- **Between the dates below, no outcome is read.** At any time the runner may check inputs
  without reading an outcome. The check reports, for each gameweek from the first scored
  one, the capture the ledger's decision names and that capture's own target, whether the
  handoff and the `ep_next` field are both present, how many players the capture has no
  `ep_next` for, and which weeks are missing and why. A week whose capture targets another
  gameweek shows up there before any outcome is read. The check is posted on #1004 after
  each settle from gameweek 7 to gameweek 12 (step 3 of the issue).
- **Reading 1**, after the sixth gameweek counted from the first scored one settles. With an
  on-time merge that is gameweek 12 (deadline 2026-11-27T18:30:00Z), reading 1 taken once
  it settles, and the verdict posted on #1004 by 2026-12-04T12:00:00Z. All four readings are
  taken over the scored weeks up to it. If missing weeks leave fewer than six scored, the
  reading still happens on that date, prints no interval, ships nothing, and reading 2 stays
  where it is. (Reading clock accepted by the owner on 2026-10-14.)
- **Reading 2**, after gameweek 20 settles (deadline 2027-01-05T18:00:00Z): all four readings
  over the scored weeks up to gameweek 20. It can only stop or confirm; it cannot ship.

There is no reading before, between or after these, and none taken once more. If the control
handoff stops being served, or the weekly runs stop, later weeks are missing for that reason
and the readings still happen on the same dates with the weeks they have. The 2027-28 season
is not covered: a new season needs a new protocol.

## The ship rule and the stop rule

Let `n` be the number of scored gameweeks that enter reading 1's accuracy series.

**Ship rule, at reading 1.** The candidate ships only when `n >= 6` and all three hold:

- (a) on the decision population, the 90 per cent interval of the per-week MAE difference,
  candidate minus control, has its upper end below 0;
- (b) on the same population, the pooled within-position Spearman gain, candidate minus
  control, averaged over positions with equal weight, is at least 0, and no position loses
  more than 0.01;
- (c) on member plans, the mean of the per-week member means, candidate minus control, is at
  least 0.

The verdict is **`ship`** when all three hold, **`insufficient_evidence`** when `n < 6`, and
otherwise **`no_ship`**, with each clause reported whether or not another fails.
`(default 3 of #1004, accepted 2026-10-14)`

**Stop rule, at reading 2.** Over the scored weeks up to gameweek 20, let `[lo_d, hi_d]` be
the interval of the per-week member means (reading 3) and `[lo_a, hi_a]` the interval of the
per-week MAE difference on the decision population (reading 1), both candidate minus
control. The record says **`revert`** when `hi_d < 0` or `lo_a > 0`, and otherwise
**`confirmed`**. Each interval needs six scored weeks; one that cannot be printed cannot
trigger the stop. Reading 2 ships nothing: a `no_ship` at reading 1 is final for this
season, and the stop rule applies to the production path only if the ship step has merged.

**Control version.** A control handoff version that changes mid-protocol is scored as served
and reported per version, with the pooled figure beside the per-version ones. If the blend
has shipped before reading 2, the control at reading 2 is still the unblended `ours_decided`,
which the ship step keeps beside the blended forecast for this purpose (step 5 of #1004).

## What ships and what does not

- `ep_next` stays a yardstick in production unless the ship rule passes. Until then no file
  under `src/squadopt/live/` or `src/squadopt/prediction/` changes for this candidate, and
  the docstring at `src/squadopt/data/sources/fpl_live.py:2361-2363` stays as it is.
  `(default 1 of #1004, accepted 2026-10-14)`
- Only the ship pull request rewrites that docstring. On a `ship` verdict, the blend is
  applied after availability in `src/squadopt/live/recommendation.py`, after the
  `apply_availability` call at `:602`, and the projection diagnostics name it; nothing under
  `src/squadopt/prediction/` or `src/squadopt/features/` changes. A capture with no `ep_next`
  field publishes the control under the control's label, never under the blend's. The live
  audit keeps the unblended forecast beside the blended one so its yardstick stays
  independent. No member-facing string changes. The release to main happens on the owner's
  yes, and İbo reviews the ship pull request because the projection is his lane.
- Steps 1 to 4 of #1004 touch only `docs/`, `scripts/` and `src/squadopt/experiments/`, and
  change nothing that is published. The builder is the one named on #1004.
  `(default 4 of #1004, accepted 2026-10-14)`
- On a `revert` at reading 2, the revert pull request is live before 2027-01-23T13:30:00Z,
  the gameweek 22 deadline.

## Deadline

This document merges before 2026-10-17T10:00:00Z, the gameweek 7 deadline, so that gameweek
7 is the first scored week and reading 1 follows gameweek 12. The deadlines it is paced by,
from `web/public/data/fixtures.json`:

| Gameweek | Deadline |
| --- | --- |
| 7 | 2026-10-17T10:00:00Z |
| 9 | 2026-10-31T11:00:00Z |
| 12 | 2026-11-27T18:30:00Z |
| 13 | 2026-12-02T18:30:00Z |
| 15 | 2026-12-12T13:30:00Z |
| 20 | 2027-01-05T18:00:00Z |
| 22 | 2027-01-23T13:30:00Z |

Nothing enters the merge queue while a weekly run is under way: even a docs-only merge
moves `origin/develop`, and the publish stage then refuses the run
(`check_publication_base`, `src/squadopt/platform/weekly_publish.py:158-178`).

## What this protocol does not do

- It fits nothing and tunes nothing. It reads no gameweek before the first scored one, and
  no gameweek of any earlier season.
- It reads one arm only. The restricted arm the owner may choose instead (the blend applied
  only to players our rule did not name who had under 60 minutes a week before the deadline)
  is a different candidate and would need its own wording here before the merge. A separate
  `chance_of_playing` arm is not read: it is already in the control, named players are not
  where the gap is, and how it compounds with the fitted appearance side is #531 item 1.
- It does not read three- or five-week windows, chips, Top 100 weights, the manager's word,
  rival strategies, or the football model.
- It reads no member's behaviour: every plan it scores is computed from the capture, and
  whether anybody followed it does not matter.
- Nothing in it is member-facing. It writes nothing under `data/` and replaces no handoff.
- It does not repair the audit's pooled block (#998 item 6), re-ask #712, or refresh
  availability on the device (#980).

## Where the record lives

The record follows ADR 0003 (`architecture/decisions/0003-measurement-artifacts.md`):

- **Record, committed.** `docs/appearance_game_forecast.json` with its markdown twin and a
  row in `measurements_index.md`, written at reading 1. It holds, per gameweek: the scored
  capture and its own target, the handoff fingerprint and model version, the number of
  players without `ep_next`, each population's counts, readings 1, 2 and 4 per arm, reading
  3's counts and means with the planner revision and budget, and the pooled statistics with
  the verdict or the reason there is none. Reading 2 is recorded in the same files, in its
  own block, and reading 1's block is reproduced unchanged beside it.
- **Evidence, not committed.** The per-player forecast and outcome rows and the per-member
  plans go under `artifacts/`. They are expansions of licence-restricted captures.
- **Operational state, read only.** Captures, handoffs and the ledger are read through their
  existing readers.

## Reproduction

The runner is step 2 of #1004: a module under `src/squadopt/experiments/` and
`scripts/measure_appearance_game_forecast.py`, to be added in its own pull request before
gameweek 9's deadline, with an input-check mode that opens no settled outcome. Its tests pin
the blend on a hand-computed fixture, including a player with no `ep_next` who is kept at the
control and not at zero; show that the input-check mode opens no settled outcome; mark as
missing a week whose capture targets another gameweek; and pin every difference's sign as
candidate minus control. It changes no live path.
