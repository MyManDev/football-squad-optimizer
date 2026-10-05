# Planner policy chain, 2026-27: pre-registration

This document is declared before any week it scores and binds from the commit that merges it.
It changes no planner, default, published document or member page, promotes nothing, and reads
no outcome of the gameweek it decides or of a later one before its first reading.

## The question

On 2026-10-02, under the experimental football model, a member's three- and five-week window
is planned by `plan_transfer_horizon` in `src/squadopt/live/transfers.py`. Its planner source
is the one `site-2026-27-gw06-fix11` released. It routes such a window three ways:

- **Observed.** When the capture states a 25, 50 or 75 per cent chance of playing for a held
  player who meets the conditions of `availability_observations` in
  `src/squadopt/live/football_observations.py`, the window is solved by
  `expected_lineup_observed_window_v4` (`src/squadopt/planning/observed.py`).
- **Expected.** Otherwise, when the forecast carries appearance probabilities and the window
  has at least five deterministic units, it is solved by `expected_lineup_window_v1`
  (`src/squadopt/planning/expected_window.py`). That route ranks two guarded proposals on one
  expected lineup utility.
- **Guarded.** Otherwise, it is solved by `sequential_certified_window_v1`
  (`src/squadopt/planning/guarded.py`).

Each routed window may also make a second move in a week from two banked free transfers
(`allow_two_free_transfers` in `src/squadopt/planning/models.py`).

Windows under the current model keep the full-window solver,
`optimize_transfer_plan(..., protect_hold=True)` in `src/squadopt/planning/optimizer.py`. That
is also the path a football window took before #907.

These routes changed with each of #907, #909, #911, #915 and #919, and the expected route again
with #948 (`expected_lineup_window_v2` at develop 260f174e). The model the option serves changed
too: `football_joint_role_minutes_v1` landed with #924 and
`football_joint_role_retained_history_v1` with #948, and since `site-2026-27-gw06-fix14` the
option serves the latter. So the arm this protocol calls `served` is whatever
`plan_transfer_horizon` routes to at the frozen commit (rule 3), and its records name the
version.

The evidence for the two routes is in-forecast. #907 shipped functional checks and no
measurement. #909's record, `docs/research/football_information_windows.md`, is a four-case
comparison on a synthetic eight-player roster in which the information menu gained nothing over
its own baseline. #911 added to the same record a fourteen-case completion matrix on one captured
forecast of GW6 to GW10, in which every selection retained the baseline; the record calls it
completion and accounting evidence, not prospective football accuracy. A sequential construction certified inside a full-window solve, the method
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

I expect contrast A to sit near zero. Both arms solve the same window under the same policy and
the same configured work. They differ in the search, and where the observed or expected route
applies, in a final choice made on expected lineup utility, not on points alone. I expect contrast B to be above zero and below its detectable effect, and both final
intervals to include zero. These are stated priors, and no clause reads them.

## 1. Identity and binding

1. The protocol is `planner_policy_chain_v1`, for season 2026-27, from its first chain week
   through GW38.
2. It binds from the commit that merges it. The first chain week is the first gameweek whose
   deadline falls after the later of two merges: this document's, and that of the runner
   `scripts/measure_planner_policy_chain.py`. A merge is the commit on develop's first-parent
   line that added the file, compared with its first parent: the squash commit, or a merge
   commit, never the feature commit that wrote it. Its instant is that commit's committer
   instant. The target is GW6, whose deadline the bootstrap of
   capture `fpl-live-20260922T214539Z-364991a4f832` puts at 2026-10-10T10:00:00Z. The owner's
   answer on #632 (5948324329) holds GW6 to two dates: this document merged by 6 October and the
   runner by 8 October, each by the end of that day in UTC (before 2026-10-07T00:00:00Z and
   2026-10-09T00:00:00Z). If either misses its date, the first chain week is GW7, or the first
   deadline after the later merge when that is later still. The reading dates do not move, so a
   later start leaves fewer weeks to read. A first chain week fixed before any of its inputs
   exist cannot be chosen after its outcome is seen, and an earlier week is never relabelled as
   the start.
3. Every decision is computed from the runner's merge commit, the frozen source, and `served`
   is the routed planner at that commit, whatever version strings it carries. The first run
   refuses unless HEAD is that commit. It records the commit, the sha256 of this document's
   bytes and of the runner's at that commit, the Python version, the operating system and
   architecture, and the installed OR-Tools, numpy and pandas versions. A later run on a
   different commit, document, runner, interpreter, platform or package version is refused.
   Each reading states, for each of its weeks, whether the live release carried the same
   planner source, and the same binding source (`load_switch_inputs` and the modules it calls,
   rule 6), as the frozen commit.
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
6. The forecast is the served football artifact for that capture, read and bound as the service
   binds it: `load_switch_inputs` in `src/squadopt/platform/advice_switches.py`, with the
   capture's own inputs and the fingerprint of the served baseline handoff for that capture
   (`handoff_fingerprint_for` in `src/squadopt/platform/capture_context.py`), once
   `read_football_forecast` in `src/squadopt/live/football_artifact.py` has read the file with
   those inputs. The runner is given the artifact root and the handoff root the backend served
   the week from (`SQUADOPT_BACKEND_ARTIFACT_ROOT`, which `artifacts/backend-artifact-root.json`
   selects, and `SQUADOPT_BACKEND_HANDOFF_ROOT`), and each receipt names both. One run decides
   only weeks served from the same two roots: where the backend's roots changed between weeks,
   the operator decides through the last week of the old ones (`--through-gameweek`) and
   continues with the new. The runner binds with no configured club-news source, so the only
   news in the chain's forecast is what a ready bundle seals. So a ready bundle, the news it
   seals and the participation evidence apply to the chain's forecast as the service at the
   frozen commit applies them, which is how they applied to the served one in a week whose live
   release carried the same binding source (rule 3). A capture with no served baseline handoff
   is not served, so its week is missing. A week the service refuses to bind (for example a
   ready bundle that fails its checks or whose handoff is not the served one, a joint model
   without a complete ready bundle, sealed news that cannot be resolved, a sealed component
   basis that is unavailable), or on which it raises, is missing for the reason the service
   states or the error it raises, as the backend serves no football input for either; the
   receipt records which. The artifact's model version must be one this protocol admits,
   `football_team_share_v1`, `football_joint_role_minutes_v1` or
   `football_joint_role_retained_history_v1`, and one the reader at the frozen commit accepts;
   `football_contextual_v3`, which that reader also accepts, is not admitted. The version is
   read from the artifact's own `model_version` field before any reader runs, so a week of any
   other version whose fingerprint verifies is missing as that and never as unreadable. Its
   fingerprint must verify, and its file's modification time, as the file system reports it,
   must fall before the deadline. So must the modification times of the ready bundle's marker
   (`football_bundle_path` in `src/squadopt/platform/football_bundle.py`) and of the components
   file beside the artifact (`football_components_path` in
   `src/squadopt/platform/football_minute_basis.py`), where either exists: the service could
   not have bound a file written later, so a week where either was written at or after the
   deadline is missing.
   The runner reads the file's bytes first, records their sha256, the fingerprint and the
   modification time, and copies those bytes into the chain's evidence; the reader and the
   service read the file again, and a file whose fingerprint changes between those reads makes
   the week missing. The artifact is never rebuilt, never borrowed from another capture and
   never written to. Inputs read on a machine
   other than the one that wrote them are copied with their modification times kept (for
   example `robocopy /COPY:DAT /DCOPY:T` or `rsync -t`); a copy that loses them makes the week
   missing, and that is never repaired. A producer change that keeps the version name is
   recorded with its first week; those weeks are pooled and also reported apart. A change from
   one admitted version to another is recorded the same way, with each week's own version, and
   no two are ever relabelled as one (rule 29).
7. The season rules are `read_season_rules` in `src/squadopt/live/rules.py`, on the same
   capture.
8. No archive, no member or entry payload and nothing captured after the week's deadline
   enters a decision. The served baseline handoff is used only for its fingerprint, which a
   ready bundle must match as it must when served (rule 6); no handoff projection enters a
   decision. Later captures are read only for the deadlines they state (rule 5) and for the
   inventory each receipt lists; no outcome they carry is read. `read_snapshot` verifies every
   payload of a capture, including entry picks and earlier live payloads a capture may carry,
   and the service's check of a ready bundle (rule 6) reads every file the bundle seals,
   including its copy of the handoff and the league site's member and entry documents; the
   decision step reads none of them for a decision, and no record names them. What the served
   forecast's producer fitted on differs by version and is recorded from the artifact (rule
   38); this protocol asserts nothing about it, and the chain neither fits nor reads that
   history.

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
    fee on later purchases. For a three- or five-week football window it routes, that policy also
    allows a second move in a week from two banked free transfers (`allow_two_free_transfers`),
    and `hold` plans under the same policy. A truncated window (rule 14) is not routed and keeps
    one move. The one-week arm uses the same policy uncapped, as the product serves
    one week, so contrast B compares a capped window with an uncapped week and does not separate
    the horizon from the cap. Whenever `served` and `hold` plan from the same state, as they do
    in the first chain week, the runner checks that their plans carry the same configuration and
    horizon fingerprints, and refuses a mismatch.
13. `served` records:
    - the route its call took (observed, expected, guarded, or neither) and that route's
      version string;
    - the observed window's outcome (`observed_window.status`): `compared`, or the reason it is
      incomplete, in which case the plan is the guarded baseline solved at 40 per cent of the
      units;
    - the expected window's outcome and chosen proposal (`expected_lineup_window.status` and
      `chosen`);
    - whether the guarded construction completed (`sequential_incumbent.seed_completed`).

    Contrast A is also split by these, descriptively.
14. A window that would reach past GW38 is truncated to min(w, 39 - g) weeks: GW35 to GW38 for
    five weeks and GW37 and GW38 for three. The product refuses such a window, and the routed
    planner needs three or five weeks, so a truncated week is not the served planner. There
    `served` takes the full-window solver at twenty units a week with its hold probe outside
    that limit, and at one week the uncapped one-week policy without the acquisition fee;
    `hold` keeps its split. Truncated weeks are played, so that each state continues, are
    labelled truncated and enter neither primary contrast; they are reported beside them. A
    contrast therefore scores at most 31 weeks, GW6 to GW36.
15. In every arm no chip is offered, no preference is set, the Top 100 weight is 0 and the
    manager's word switch is off. The news the service seals into a week's forecast (rule 6) is
    part of that forecast, not a switch, and reaches every arm alike.
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
    served baseline handoff for the capture, no artifact, an artifact of another model version,
    one that fails its fingerprint, changes while it is read or does not bind to the capture,
    one written at or after the deadline, a ready bundle marker or components file written at
    or after the deadline, or a binding the service refuses or raises on (rule 6). In a missing
    week every arm
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
    transfers, bank and sale value apart are secondary and descriptive only. Each contrast is
    also reported for each admitted model version on its own weeks, with the first week of each;
    the pooled figure stays primary, because every arm in a week plans on that week's one
    forecast, so each week's paired difference lies within one version.
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
    only what the football option already produced. If the football option is withdrawn, or is
    served under a model version rule 6 does not admit, later chain weeks are missing for that
    reason. At
    the interim, gross points, hits, free transfers, bank and sale value appear only as paired
    differences between arms; each arm's absolute totals appear only at `gw38`. No chain reading
    may be used to withdraw, change or re-time the football option.

## 10. Records and operation

36. The evidence (input receipts, forecast copies, each arm's decision records and the weekly
    manifests) stays uncommitted under `artifacts/planner_policy_chain/` until the final reading
    is committed. Per week it holds the capture id, fingerprint, capture instant and deadline, the artifact's
    sha256, fingerprint, model version and modification time, and the binding the service at the
    frozen commit made (rule 6): the names of the artifact and handoff roots it was given,
    `ready_bundle_sha256` and the marker's modification time, `handoff_fingerprint`,
    `rotation_table_sha256`, `components_sha256` and the components file's modification time,
    whether the components bound, the decision information (`football_decision_information_v1`,
    with its revision, which the participation version enters, and whether the news and the
    components bound) and the service's notes on the football binding, without its Top 100
    notes (the chain's call carries no projected table, and rule 15 sets that weight to 0) and
    with every file path replaced (rule 38), each recorded as absent when the service had none.
    Per arm it
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
    producer may read archive seasons the chain does not, and which ones depends on the producer
    and its version, so this protocol asserts none. Each receipt records them from the artifact
    itself: `forecast_archive_seasons`, the seasons whose archive files the artifact hashes, with
    the artifact's training row count and latest training kickoff as it states them, its
    `training_selection`, and from `role_metadata` the role model's `version` and
    `role_feature_version`. A field the artifact does not carry is recorded as absent and never
    filled in.
39. The decision step runs once after each deadline, as one heavy job at a time, never on a
    Tuesday or Friday and never during a weekly run or a rehearsal. It reads captures and
    football artifacts read-only and writes only under `artifacts/planner_policy_chain/`. It
    never writes under `data/` or elsewhere under `artifacts/`, never starts, stops or calls
    the backend or port 8000, and never opens a live store or `data/runtime`. The operator
    announces each run on the tracking issue.
40. Who runs the decision step and the scorer, and on which machine, was asked on #632 as
    Question PC1. The owner answered on 2026-10-02 (5948324329): the owner runs both on the
    owner's machine, which writes the football artifacts and keeps the captures. No decision is
    computed before 2026-10-11T10:00:00Z, the end of the 9 to 11 October freeze: the runner
    refuses an earlier run before it takes its lock, reads its inventory, writes or solves. The
    first computation reads GW6's decision capture and served forecast and no match outcome.
    Another operator or machine needs a new Answer, and
    silence is not one; any other machine copies its inputs as rule 6 says. However late a
    decision is computed, the chain starts at its first chain week and decides weeks in order,
    each from its own capture and artifact, and the ready bundle and components file the
    service binds, if they are still on disk with a write time before that week's deadline; a
    week whose inputs are gone is missing. Each decision is a function of the
    frozen source and of inputs written before its week's deadline, so when it is computed does
    not change it. If no chain has started by gameweek 21's deadline, the runner refuses to start
    one, nothing is read and the protocol lapses unrun.

## 11. What this does not claim

The chain uses constructed squads, not members' squads, over one season. A difference between
arms is a difference between these policies on these squads under the served football forecast.
It is not a forecast of any member's result. It is not evidence about windows under the current
model, about later releases whose planner or binding source differs from the frozen commit,
about truncated windows, or about whether the forecast's chances of playing are calibrated. It
does not test chip timing, the Top 100 weight, the manager's word or the preferences. In
contrast B the one-week planning table carries no appearance probability while the windows'
tables do, and `lineup_fields` orders the bench by it when it is present, so the two arms' bench
orders follow different rules. Where the observed or expected route applies, `served` also makes
its final choice on expected lineup utility, while `hold` and the one-week path choose on
points. So neither contrast separates the search from that choice. Where a week is served under
a ready bundle, every arm plans on the forecast as the service at the frozen commit binds it,
sealed news and participation evidence included; the chain does not separate the planner from
that binding. A week without a ready bundle is bound with no configured club-news source (rule
6), so news the backend bound from its own configuration in such a week is not in the chain's
forecast.
