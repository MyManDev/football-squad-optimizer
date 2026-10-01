# Planner policy chain, 2026-27: pre-registration

This document is declared before any week it scores and binds from the commit that merges it.
It changes no planner, default, published document or member page, promotes nothing, and reads
no outcome of the gameweek it decides or of a later one before its first reading.

## The question

On 2026-10-01, under the experimental football model, a member's three- and five-week window
is planned by `plan_transfer_horizon` in `src/squadopt/live/transfers.py`. When the capture
states a 25, 50 or 75 per cent chance of playing for a held player who meets the conditions of
`availability_observations` in `src/squadopt/live/football_observations.py`, the window is
solved by `bounded_observed_window_v1` (`src/squadopt/planning/observed.py`, released in
`site-2026-27-gw06-fix7`); otherwise by `sequential_certified_window_v1`
(`src/squadopt/planning/guarded.py`, released in `site-2026-27-gw06-fix6`). #911, merged the same
day for the next release, replaces the observed route with `complete_observed_window_v2`. Windows
under the current model keep the full-window solver, `optimize_transfer_plan(..., protect_hold=True)`
in `src/squadopt/planning/optimizer.py`, which is also the path a football window took before #907.
These routes change between releases, so the arm this protocol calls `served` is whatever
`plan_transfer_horizon` routes to at the frozen commit (rule 3), and its records name the version.

The evidence for the two routes is in-forecast. #907 shipped functional checks and no
measurement. #909's record, `docs/research/football_information_windows.md`, is a four-case
comparison on a synthetic eight-player roster in which the information menu gained nothing over
its own baseline. A sequential construction certified inside a full-window solve, the method
the guarded route ships, was measured in #906, still open, as forecast utility on one capture,
`fpl-live-20260922T214539Z-364991a4f832`, with two constructed squads over a fourteen-week
forecast. `guarded.py` says future performance is not established.

Realized churn has been measured, but only on four development seasons under the current
model's projections. A rolling four-week planner without a cap paid 14.5 hit points per
four-week window against 5.8 for the weekly baseline (`docs/planner_horizon_rolling_note.md`),
and a three-week rolling planner capped at one transfer a week drew level with the weekly
control, +0.22 points a gameweek [-1.14, +1.39] over 147 paired weeks
(`docs/transfer_discipline_note.md`). No routed football window has been measured on realized
points.

This protocol asks, prospectively and on realized points: when each arm plays only the first
week of its plan, carries its own state forward and plans again at the next deadline, how do the
routed football window planner, the full-window solver it replaced and the one-week path
compare over the rest of the season? It also records, at each deadline, part of what
`docs/research/planner_state_and_learning.md` names as the precondition for a later policy
experiment: the forecast and its write time, the purchase lots, bank and free transfers, each
arm's selected action and the realized team score. It does not record alternative actions at
one state, later observations of individual players or per-player outcomes.

## What is expected, declared before any week is read

The closest committed analogue is the capped three-week rolling planner against the uncapped
weekly control on four development seasons: variant `L3_chips_reserve_hit8_cap1_ftv0` in
`docs/transfer_discipline_rolling.json` minus variant `L1_chips_reserve_hit8_capnone_ftv0` in
`docs/transfer_discipline.json`, week by week from the `weeks` of their chains. Over 147 paired
gameweeks the mean difference is +0.97 points a gameweek, with a standard deviation of 11.60 and
a lag-one autocorrelation of 0.19. One season of four carries it: +268, -40, -21 and -64 points
by season. Both arms of that analogue use the current model's projections, play chips by the
reservation rule and plan with a hit cost of 8 while charging 4. The chain's arms share the hit
costs, use the football forecast and play no chip. `tests/unit/test_planner_policy_chain_prereg.py`
recomputes every number in this paragraph and the next from those two files.

At that standard deviation, `detectable_effect` in `src/squadopt/evaluation/live_series.py`
under `DetectionPolicy(confidence_level=0.90, power=0.80)` is 7.45 points a gameweek at 15
scored weeks and 5.18 at 31. It treats weeks as independent, which is optimistic at a positive
autocorrelation. The analogue's mean is below both.

I expect contrast A to sit near zero: both arms solve the same window under the same policy and
the same configured work, and differ only where a budget-limited search stops in a different
place. I expect contrast B to be above zero and below its detectable effect, and both final
intervals to include zero. These are stated priors, and no clause reads them.

## 1. Identity and binding

1. The protocol is `planner_policy_chain_v1`, for season 2026-27, from its first chain week
   through GW38.
2. It binds from the commit that merges it. The first chain week is the first gameweek whose
   deadline falls after the later of two merges: this document's, and that of the runner
   `scripts/measure_planner_policy_chain.py`. The target is GW6, whose deadline the bootstrap of
   capture `fpl-live-20260922T214539Z-364991a4f832` puts at 2026-10-10T10:00:00Z. If either
   merges later, the first chain week moves to the next deadline; the reading dates do not move,
   so a later start leaves fewer weeks to read. A first chain week fixed before any of its inputs
   exist cannot be chosen after its outcome is seen.
3. Every decision is computed from the runner's merge commit, the frozen source, and `served`
   is the routed planner at that commit, whatever version strings it carries. The first run
   refuses unless HEAD is that commit. It records the commit, the sha256 of this document's
   bytes and of the runner's at that commit, the Python version, the operating system and
   architecture, and the installed OR-Tools, numpy and pandas versions. A later run on a
   different commit, document, runner, interpreter, platform or package version is refused.
   Each reading states, for each of its weeks, whether the live release carried the same
   planner source as the frozen commit.
4. A fault found in the runner after it binds is fixed in its own pull request, which changes
   only the runner or the scorer. The fixed runner runs from the frozen commit with only that
   file replaced, recomputes the last week already decided and must reproduce it exactly before
   it decides another. That pull request adds the recompute-and-compare step to the runner and
   the identity rule that admits the replaced file, because the runner as it binds refuses a
   changed runner. The fix and its first week are a declared deviation in every later record,
   and decisions already written stand. A change to what an arm does is not a fix: it needs a
   new protocol.

## 2. What each week reads

5. The decision capture of gameweek g is the last `fpl-live` capture, by capture instant, whose
   own target is g: `read_inputs(snapshot, season="2026-27")` in
   `src/squadopt/live/recommendation.py` returns a deadline whose gameweek is g. Two captures at
   the same latest instant make the week missing. This is the rule
   `scripts/check_football_prospective_inputs.py` applies for `docs/football_prospective_prereg.md`,
   so both protocols read the same capture each week. Which capture is the last is known only
   once the deadline has passed, so the runner decides gameweek g only after its deadline,
   refuses an earlier decision, and decides weeks in order, each once. A capture taken after
   every published deadline has closed targets no gameweek and is left out. Each week's receipt
   lists every capture whose own target is that week, with its instant, so the choice can be
   checked against the inventory later.
6. The forecast is the served football artifact for that capture, read by
   `read_football_forecast` in `src/squadopt/live/football_artifact.py` with the capture's own
   inputs. Its model version must be `football_team_share_v1`, its fingerprint must verify, and
   its file's modification time, as the file system reports it, must fall before the deadline.
   The runner reads the file's bytes once, records their sha256, the fingerprint and the
   modification time, and copies those bytes into the chain's evidence. The artifact is never
   rebuilt, never borrowed from another capture and never written to. Inputs read on a machine
   other than the one that wrote them are copied with their modification times kept (for
   example `robocopy /COPY:DAT /DCOPY:T` or `rsync -t`); a copy that loses them makes the week
   missing, and that is never repaired. A producer change that keeps the version name is
   recorded with its first week; those weeks are pooled and also reported apart.
7. The season rules are `read_season_rules` in `src/squadopt/live/rules.py`, on the same
   capture.
8. The decision step uses no archive, no handoff, no member or entry payload and nothing
   captured after the week's deadline. `read_snapshot` verifies every payload of a capture,
   including entry picks and earlier live payloads a capture may carry; the decision step reads
   none of them. The served forecast was fitted by its producer on settled history, including
   settled 2026-27 weeks before the capture; the chain neither fits nor reads that history.

## 3. States

9. Three constructed squads, by the rule of `scripts/measure_shortlist_matrix.py`: squad
   budgets of 1000, 950 and 900 tenths, with total funds of 1000, 1000 and 900 and with one, two
   and zero free transfers. Each is built once, from the first chain week's forecast table with
   the capture's availability, by `optimize_squad` in `src/squadopt/optimization/optimizer.py`
   at linearization level 2 under that runner's configuration: no bench weight, 60
   deterministic units and a 120-second wall ceiling. A squad not proved OPTIMAL at 60 units is
   built once more at 240. A squad still not proved drops only its own chains, and the record
   lists it. If the first chain week is missing (rule 21), the squads are built from the first
   later week that is not; that week becomes the first chain week, and the skipped weeks are
   listed.
10. Each player's purchase price is the first chain week's captured price, so every purchase
    lot is known. The bank is the funds less the squad's cost, no chip has been used, and the
    squad's sale value is not stated, so sale prices follow the game's rule player by player.
    Every arm starts from the same state for each squad, which makes fifteen chains.

## 4. Arms

11. Every arm calls an existing entry point, which it reads and never changes, at twenty
    deterministic units per forecast week, so arms that solve the same window get the same
    configured work.

    | Arm | Call | Weeks | Units | Wall ceiling |
    | --- | --- | --- | --- | --- |
    | `served_3`, `served_5` | `plan_transfer_horizon` exactly as `solve_window_plan` in `src/squadopt/application/advice.py` calls it, with `WINDOW_DETERMINISTIC_UNITS_PER_WEEK`, `WINDOW_WALL_CEILING_SECONDS` and `WINDOW_LINEARIZATION_LEVEL`, and with the chain's own held squad in place of the member's picks | 3, 5 | 60, 100 | 1800 s |
    | `hold_3`, `hold_5` | the runner's copy of the preparation `plan_transfer_horizon` makes, then `optimize_transfer_plan(..., protect_hold=True)` at `WINDOW_LINEARIZATION_LEVEL`, with its primary limit one unit short so that the 1-unit hold probe brings it to the same total | 3, 5 | 59 and 99, plus the 1-unit hold probe | 1800 s |
    | `one_week` | `plan_transfers` in `src/squadopt/live/transfers.py`, with an explicit configuration equal to `PLAN_DETERMINISTIC_TIME_LIMIT` and `PLAN_WALL_CEILING_SECONDS` | 1 | 20 | 300 s |

12. The window arms use the member transfer policy `plan_transfer_horizon` applies to a window:
    a planning hit cost of 8 with 4 charged, at most one transfer a week and the captured sale
    fee on later purchases. The one-week arm uses the same policy uncapped, as the product serves
    one week, so contrast B compares a capped window with an uncapped week and does not separate
    the horizon from the cap. Whenever `served` and `hold` plan from the same state, as they do
    in the first chain week, the runner checks that their plans carry the same configuration and
    horizon fingerprints, and refuses a mismatch.
13. `served` records the route its call took (observed, guarded, or neither), that route's
    version string, the observed window's outcome (`observed_window.status`: `compared`, or the
    reason it is incomplete, in which case the plan is the guarded baseline solved at 40 per
    cent of the units) and whether the guarded construction completed
    (`sequential_incumbent.seed_completed`). Contrast A is also split by these, descriptively.
14. A window that would reach past GW38 is truncated to min(w, 39 - g) weeks: GW35 to GW38 for
    five weeks and GW37 and GW38 for three. The product refuses such a window, and the routed
    planner needs three or five weeks, so a truncated week is not the served planner. There
    `served` takes the full-window solver at twenty units a week with its hold probe outside
    that limit, and at one week the uncapped one-week policy without the acquisition fee;
    `hold` keeps its split. Truncated weeks are played, so that each state continues, are
    labelled truncated and enter neither primary contrast; they are reported beside them. A
    contrast therefore scores at most 31 weeks, GW6 to GW36.
15. In every arm no chip is offered, no preference is set, the Top 100 weight is 0 and the
    manager's word is off.
16. Not chained, with the reasons. An explicit lookahead on a rebuilt tail (#904) does not use
    the served forecast. The automatic chip strategy is refused to members. The
    certification-only ablation and the hint variants answer other questions. A current-model
    arm would compute the football protocol's quantities (rule 35).

## 5. Each week

17. Only the first week of each arm's plan is played. At the next deadline the arm plans again
    from its own state, which is never reset.
18. The state carries forward as the ledger's `_package_decision` in
    `src/squadopt/live/transfers.py` carries it. An outgoing player's purchase price is dropped
    and an incoming player's is that capture's price. The bank is the first week's
    `bank_after_tenths` and the free transfers its `free_transfers_for_next_gameweek`. Next
    week's sale prices follow `sell_price_tenths` in `src/squadopt/planning/pricing.py` at that
    capture's prices and fee. The runner derives the bank a second, independent way; a mismatch
    stops the run before anything of that week is written, as a fault under rule 4.
19. The lineup played is `lineup_fields` in `src/squadopt/application/lineup_publication.py`,
    read from the first week: the eleven, the bench order, the captain and the vice-captain.
20. A FEASIBLE plan is played as the product would serve it. The share of plans proved OPTIMAL
    by their own search is reported; an observed comparison is published FEASIBLE and is not
    counted as proved. No optimality is claimed for an unproved plan.

## 6. Missing weeks and failures

21. A week is missing when there is no own-target capture, a tie at the latest instant, no
    artifact, an artifact of another model version, one that fails its fingerprint or does not
    bind to the capture, or one written at or after the deadline. In a missing week every arm
    holds: no transfer, free transfers of min(f + 1, the maximum in the season rules of the last
    capture the chain read), and purchase prices and bank unchanged. The week is not scored and
    is listed with its reason. It is never filled from another capture or from a forecast built
    after the deadline. A blank or double gameweek needs no rule of its own: the forecast carries
    its fixtures and the outcome capture what was played.
22. An arm fails a week when its call returns no plan, raises, is stopped by its wall-clock
    ceiling, has its hold probe stopped by the probe's own 30-second clock before its unit, or
    yields an incomplete lineup. A plan the clock stopped fails here although the product's
    one-week path would publish it, because a clock-cut plan is a function of the machine and
    could not be reproduced. The failure is recorded, and the arm holds as in rule 21 and plays
    its held team: last week's fifteen, eleven, bench order, captain and vice-captain, or in the
    first chain week the lineup its squad was built with. That week is scored and stays in the
    pairs, so a failing arm bears what its failure costs; each contrast is also reported without
    failed weeks. A failed week is never retried, given a different budget or replaced by
    another arm's action.
23. If a held player is absent from a capture's roster, that chain is blocked from that week: it
    makes no decision from then on, contributes no pair and is listed. No sale is invented.
24. Records are written once, by `write_document_once` in `src/squadopt/data/atomic.py`. Work
    and clock fields are kept out of the replay identity, because the deterministic time used
    varies in its last digit between runs. A recomputation that disagrees on any decision is
    refused, and the first record stands. Every run appends a line to a run log in the output
   directory, with its instant, the weeks it decided and why it stopped. The operator posts the frozen
    commit and each week's manifest sha256 on the chain's tracking issue, and each reading checks
    the manifests against those receipts.

## 7. Scoring

25. A week's outcome capture is chosen at the reading by the rule `evaluate_week` in
    `src/squadopt/application/weekly_suggestion_eval.py` uses: of the captures at or after the
    deadline whose bootstrap counts the week in `scored_gameweeks` and that hold its live
    payload, the latest. Its id is recorded. A tie at the latest instant, a rule this protocol
    adds, or no such capture leaves the week unscored with its reason, never zero, and listed.
    A week whose outcome capture changed between the two readings is listed with both scores.
26. A played week is scored by `score_recorded_advice` on `official_autosub_captain_v2`, and
    each paid transfer is charged at the game's 4 points. The planning cost of 8 never enters a
    realized number. Free transfers, bank and sale value at the end are reported, not priced.
27. The unit is the gameweek, because every arm and squad in a week shares one forecast and one
    set of outcomes. For a contrast between two arms, the week's difference is the mean, over
    the squad and window pairs both arms scored that week, of the realized difference. A pair is
    exactly zero only when both arms played the same fifteen, eleven, bench order, captain,
    vice-captain and hits; the number of such pairs is reported, and no other pair is set to
    zero.

## 8. Readings and verdicts

28. There are two readings, each taken once, after the named gameweek settles: `gw20`, interim,
    and `gw38`, final. Each covers the first chain week through the named gameweek. They fall on
    the reading dates of `docs/football_prospective_prereg.md`. No outcome capture is read
    between readings.
29. The primary contrasts are A, `served` minus `hold`, and B, `served` minus `one_week`, each
    pooled over windows 3 and 5 over the weeks that are not truncated. They are read separately,
    with no adjustment for there being two. Each window alone, `hold` minus `one_week`, each
    squad, truncated weeks, contrast A by route and outcome, and gross points, hits, free
    transfers, bank and sale value apart are secondary and descriptive only.
30. The interval is `season_aware_moving_block_interval` in
    `src/squadopt/evaluation/statistics.py` on the weekly differences, under a `PromotionPolicy`
    from `src/squadopt/evaluation/promotion.py` built with these values, stated here so that a
    later default cannot change them: a confidence level of 0.90, 5000 resamples, blocks of 4,
    deterministic seed 0 and a minimum mean improvement of 0.5 points a week. The candidate ids
    are `planner_policy_chain_v1:A` and `planner_policy_chain_v1:B`. No interval is printed
    with fewer than six scored weeks. Each reading also reports the lag 1 to 4 autocorrelations
    of each contrast and its interval with blocks of 8; no clause reads them.
31. At these counts the interval is narrower than its level. In a synthetic check with this
    function and these values, 400 replicates at each count of normal weeks with a standard
    deviation of 11.6 and a true difference of zero, the interval covered zero in 58, 76 and 82
    per cent of replicates at 7, 15 and 31 weeks, and its upper bound fell below zero in 20, 12
    and 12 per cent. At a lag-one autocorrelation of 0.2 the interval covered zero in 54, 74 and
    78 per cent, and fell below zero in 26, 15 and 10 per cent. Each record states this beside its
    intervals. The rule below is set with it in mind: no verdict at fewer than 15 weeks, no
    verdict at the interim, and one interim reading only. The check is this code, run from a
    checkout:

    ```python
    import random

    from squadopt.evaluation.promotion import PromotionPolicy
    from squadopt.evaluation.statistics import season_aware_moving_block_interval

    rng, policy = random.Random(20261001), PromotionPolicy()
    for rho in (0.0, 0.2):
        for n in (7, 15, 31):
            cover = below = 0
            for _ in range(400):
                weeks, previous = [], 0.0
                for _ in range(n):
                    previous = rho * previous + (1 - rho * rho) ** 0.5 * rng.gauss(0.0, 11.6)
                    weeks.append(("2026-27", previous))
                low, high = season_aware_moving_block_interval(
                    weeks, policy=policy, candidate_id="planner_policy_chain_v1:A"
                )
                cover += low <= 0.0 <= high
                below += high < 0.0
            print(rho, n, cover / 400, below / 400)
    ```

32. The final verdict for each contrast is the first clause that holds: fewer than 15 scored
    weeks gives `insufficient_evidence`; an upper bound below 0 gives `worse`; a lower bound
    above 0 with a mean of at least 0.5 points a week gives `better`; anything else gives
    `not_separated`. The interim records no verdict. GW6 to GW20 is at most 15 weeks, so a harm
    clause there would need every week scored and could not fire at all after a late start; the
    interim reports its intervals, counts and means and nothing else. It counts realized points
    only; free transfers and bank are reported beside it.
33. Each reading reports the minimum detectable effect at its own week count from the observed
    standard deviation, by `detectable_effect` under
    `DetectionPolicy(confidence_level=0.90, power=0.80)`, treating weeks as independent. No
    clause depends on it.
34. No verdict switches anything. A `worse` result is reported on #632, or on the chain's
    tracking issue if #632 is closed by then. Whether the routed planner stays, and whether its
    stated limit cites the record, is the owner's decision, made in the owner's own pull requests.

## 9. Separation from the football protocol

35. `docs/football_prospective_prereg.md` reads its own quantities only on its two dates, to
    protect its comparison of the football model with the current one, and it does not read
    three- and five-week windows. The chain has no current-model arm, no free squad selection,
    no difference between the football and current models and no per-player forecast error, so
    it computes none of that protocol's quantities. Its two readings fall after the same weeks
    as that protocol's two. It never asks for a capture or an artifact for its own sake: it reads
    only what the football option already produced. If the football option is withdrawn or stops
    being served as `football_team_share_v1`, later chain weeks are missing for that reason. At
    the interim, gross points, hits, free transfers, bank and sale value appear only as paired
    differences between arms; each arm's absolute totals appear only at `gw38`. No chain reading
    may be used to withdraw, change or re-time the football option.

## 10. Records and operation

36. The evidence (input receipts, forecast copies, each arm's decision records and the weekly
    manifests) stays uncommitted under `artifacts/planner_policy_chain/` until the final reading
    is committed. Per week it holds the capture id, fingerprint, capture instant and deadline,
    and the artifact's sha256, fingerprint, model version and modification time. Per arm it
    holds the route and its outcome, the solver status, the configuration and configured and
    actual work, the hits, the lineup, the state after and the decision commit. Each reading
    commits `docs/research/planner_policy_chain_gw20.json` or
    `docs/research/planner_policy_chain_gw38.json` and its markdown twin, rendered from the
    JSON, with a row in `docs/measurements_index.md`.
37. The scorer is `scripts/score_planner_policy_chain.py`. It lands in its own pull request
    before gameweek 20 settles, with tests on synthetic weeks, runs from its own merge commit,
    and refuses a reading before its gameweek settles, a reading this document does not name
    and a reading taken twice. Each record names the scorer's merge commit and the sha256 of
    its bytes.
38. Records name no member, entry or league, hold no news text and set
    `locked_holdout_accessed: false`: the chain loads no 2025-26 row. The served forecast's
    producer does: it fits on 2023-24 to 2025-26 and the capture's settled 2026-27 weeks, with
    2022-23 as priors only. So each receipt also records `forecast_archive_seasons`, the seasons
    whose archive files the artifact hashes, with the artifact's training row count and latest
    training kickoff.
39. The decision step runs once after each deadline, as one heavy job at a time, never on a
    Tuesday or Friday and never during a weekly run or a rehearsal. It reads captures and
    football artifacts read-only and writes only under `artifacts/planner_policy_chain/`. It
    never writes under `data/` or elsewhere under `artifacts/`, never starts, stops or calls
    the backend or port 8000, and never opens a live store or `data/runtime`. The operator
    announces each run on the tracking issue.
40. Who runs the decision step and the scorer, and on which machine, is the owner's decision,
    asked on #632 as Question PC1. Nothing runs before an Answer names the operator and the
    machine, and silence is not an answer. The machine is best the one that writes the football
    artifacts; any other copies its inputs as rule 6 says. If the Answer comes after the first chain week's
    deadline, the chain still starts at its first chain week and decides weeks in order, each
    from its own capture and artifact if both are still on disk with a write time before that
    week's deadline; a week whose inputs are gone is missing. Each decision is a function of the
    frozen source and of inputs written before its week's deadline, so when it is computed does
    not change it. If no chain has started by gameweek 21's deadline, the runner refuses to start
    one, nothing is read and the protocol lapses unrun.

## 11. What this does not claim

The chain uses constructed squads, not members' squads, over one season. A difference between
arms is a difference between these policies on these squads under the served football forecast.
It is not a forecast of any member's result. It is not evidence about windows under the current
model, about later releases whose planner source differs from the frozen commit, about truncated
windows, or about whether the forecast's chances of playing are calibrated. It does not test chip
timing, the Top 100 weight, the manager's word or the preferences. In contrast B the one-week
planning table carries no appearance probability while the windows' tables do, and
`lineup_fields` orders the bench by it when it is present, so the two arms' bench orders follow
different rules.
