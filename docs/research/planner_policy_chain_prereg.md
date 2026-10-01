# Planner policy chain, 2026-27: pre-registration

This document is declared before any week it scores and binds from the commit that merges it.
It changes no planner, default, published document or member page, promotes nothing, and reads
no outcome before its first reading.

## The question

A member's three- and five-week window is solved by `sequential_certified_window_v1`
(`src/squadopt/planning/guarded.py`, released in `site-2026-27-gw06-fix6`) and, on develop since
#909, by `bounded_observed_window_v1` (`src/squadopt/planning/observed.py`) when the capture
states availability; `plan_transfer_horizon` in `src/squadopt/live/transfers.py` routes between
them. Their evidence is in-forecast utility on one reused GW6 capture with constructed squads.
`guarded.py` says future performance is not established, and the explicit lookahead record says
the realized cost of churn is not measured.

This protocol asks, prospectively and on realized points: when each arm plays only the first week
of its plan, carries its own state forward and plans again at the next deadline, how do the routed
multi-week planner, the full-window solver it replaced and the one-week path compare over the
season? It is also the first collection of the per-deadline state, action and outcome records that
`docs/research/planner_state_and_learning.md` names as the precondition for any later policy experiment.

## 1. Identity and binding

1. The protocol is `planner_policy_chain_v1`, for season 2026-27, from its first chain week
   through GW38.
2. It binds from the commit that merges it. The first chain week is the first gameweek whose
   deadline falls after both this document and the runner `scripts/measure_planner_policy_chain.py`
   have merged. The target is GW6, whose deadline is 2026-10-10T10:00Z. If either merges later,
   the first chain week moves to the next deadline and nothing else changes.
3. Every decision is computed from the runner's merge commit, the frozen source. The first run
   records that commit, the sha256 of this document and of the runner, and the installed OR-Tools,
   numpy and pandas versions. A later run on a different commit, document, runner or version is
   refused. A change found necessary after that is a declared deviation in the record, and the
   decisions already written stand.

## 2. What each week reads

4. The decision capture of gameweek g is the last `fpl-live` capture, by capture instant, whose own
   target is g: `read_inputs(snapshot, season="2026-27")` in `src/squadopt/live/recommendation.py`
   returns a deadline whose gameweek is g. Two captures at the same latest instant make the week
   missing. This is the rule `docs/football_prospective_prereg.md` uses, so both protocols read the same
   capture each week.
5. The forecast is the served football artifact for that capture, read by `read_football_forecast`
   in `src/squadopt/live/football_artifact.py` with the capture's own inputs. Its fingerprint must
   verify and its file must have been written before the deadline. Its bytes are copied once into
   the chain's evidence with their sha256. It is never rebuilt, never borrowed from another capture
   and never written to. Any model version the reader accepts is used as served; the version is
   recorded, and results are split by version if more than one appears.
6. The season rules are `read_season_rules` in `src/squadopt/live/rules.py`, on the same capture.
7. The decision step reads no archive, no handoff, no member or entry document and no outcome.

## 3. States

8. Three constructed squads, by the rule of `scripts/measure_shortlist_matrix.py`: squad budgets of
   1000, 950 and 900 tenths, with total funds of 1000, 1000 and 900 and with one, two and zero free
   transfers. Each is built once, from the first chain week's forecast table with the capture's
   availability, by `optimize_squad` in `src/squadopt/optimization/optimizer.py` at linearization
   level 2 under that runner's configuration. A squad that is not proved OPTIMAL stops the chain
   before its first decision.
9. Each player's purchase price is the first chain week's captured price, so every purchase lot is
   known. The bank is the funds less the squad's cost, no chip has been used, and the squad's sale
   value is not stated, so sale prices follow the game's rule player by player. Every arm starts
   from the same state for each squad, which makes fifteen chains.

## 4. Arms

10. Every arm calls an existing entry point, which it reads and never changes, at twenty
    deterministic units per forecast week.

    | Arm | Call | Weeks | Units | Wall ceiling |
    | --- | --- | --- | --- | --- |
    | `served_3`, `served_5` | `plan_transfer_horizon` exactly as `solve_window_plan` in `src/squadopt/application/advice.py` calls it, with `WINDOW_DETERMINISTIC_UNITS_PER_WEEK`, `WINDOW_WALL_CEILING_SECONDS` and `WINDOW_LINEARIZATION_LEVEL` | 3, 5 | 60, 100 | 1800 s |
    | `hold_3`, `hold_5` | the same preparation, then `optimize_transfer_plan(..., protect_hold=True)` in `src/squadopt/planning/optimizer.py`, the path a football window took before #907 | 3, 5 | 59 and 99, plus the 1-unit hold probe | 1800 s |
    | `one_week` | `plan_transfers` in `src/squadopt/live/transfers.py`, with an explicit configuration equal to `PLAN_DETERMINISTIC_TIME_LIMIT` and `PLAN_WALL_CEILING_SECONDS` | 1 | 20 | 300 s |

11. The window arms use the member transfer policy `plan_transfer_horizon` applies: a planning hit
    cost of 8 with 4 charged, one transfer a week and the captured sale fee. The runner checks that
    the configuration fingerprint it builds for `hold` equals the one `plan_transfer_horizon`
    returns for `served` on the same inputs. `served` records which route the call took, observed
    or guarded, and that route's version string. Near the season's end a window covers
    min(w, 39 - g) weeks at twenty units a week and is labelled truncated.
12. In every arm no chip is offered, no preference is set, the Top 100 weight is 0 and the
    manager's word is off.
13. Not chained, with the reasons. An explicit lookahead on a rebuilt tail (#904) does not use the
    served forecast. The automatic chip strategy is refused to members. The certification-only
    ablation and the hint variants answer other questions. A current-model arm would compute the
    football protocol's quantities (rule 31).

## 5. Each week

14. Only the first week of each arm's plan is played. At the next deadline the arm plans again from
    its own state, which is never reset.
15. The state carries forward as the ledger's `_package_decision` in `src/squadopt/live/transfers.py`
    carries it. An outgoing player's purchase price is dropped and an incoming player's is that
    capture's price. The bank is the first week's `bank_after_tenths` and the free transfers its
    `free_transfers_for_next_gameweek`. Next week's sale prices follow `sell_price_tenths` in
    `src/squadopt/planning/pricing.py` at that capture's prices and fee. The runner derives the bank
    a second, independent way and refuses a mismatch.
16. The lineup played is `lineup_fields` in `src/squadopt/application/lineup_publication.py`, read
    from the first week: the eleven, the bench order, the captain and the vice-captain.
17. A FEASIBLE plan is played as the product would serve it. The share of proved plans is reported,
    and no optimality is claimed for an unproved one.

## 6. Missing weeks and failures

18. A week is missing when there is no own-target capture, a tie at the latest instant, no
    artifact, an artifact that fails its fingerprint or does not bind to the capture, or an artifact
    written at or after the deadline. In a missing week every arm holds: no transfer, free transfers
    of min(f + 1, the captured maximum), and purchase prices and bank unchanged. The week is not
    scored and is listed with its reason. It is never filled from another capture or from a
    forecast built after the deadline.
19. An arm fails a week when its call returns no plan, raises, is stopped by its wall-clock ceiling
    or yields an incomplete lineup. The failure is recorded, the arm holds as in rule 18, and the
    week leaves that arm's pairs. It is never retried, given a different budget or replaced by
    another arm's action.
20. If a held player is absent from a capture's roster, that chain is blocked from that week. No
    sale is invented.
21. Records are written once, by `write_document_once` in `src/squadopt/data/atomic.py`. Work and
    clock fields are kept out of the replay identity, because the deterministic time used varies
    in its last digit between runs. A recomputation that disagrees on any decision is refused, and
    the first record stands.

## 7. Scoring

22. A week's outcome capture is chosen at the reading by the rule `evaluate_week` in
    `src/squadopt/application/weekly_suggestion_eval.py` uses: of the captures at or after the
    deadline whose bootstrap counts the week in `scored_gameweeks` and that hold its live payload,
    the latest. Its id is recorded.
23. A played week is scored by `score_recorded_advice` on `official_autosub_captain_v2`, and each
    paid transfer is charged at the game's 4 points. The planning cost of 8 never enters a realized
    number. Free transfers, bank and sale value at the end are reported, not priced.
24. The unit is the gameweek. For a contrast between two arms, the week's difference is the mean over
    the squad and window pairs both arms scored that week. Weeks where both arms made the same
    decisions count as zero, and their number is reported.

## 8. Readings and verdicts

25. There are three readings, each taken once, after the named gameweek settles: `gw12` and `gw20`,
    both interim, and `gw38`, final. Each covers the first chain week through the named gameweek.
    No outcome is read between readings. The decision step reads none and may run at any time.
26. The primary contrasts are A, `served` minus `hold`, and B, `served` minus `one_week`, each pooled
    over windows 3 and 5. Each window alone, `hold` minus `one_week`, each squad, and gross points
    and hits apart are secondary and descriptive only.
27. The interval is `season_aware_moving_block_interval` in `src/squadopt/evaluation/statistics.py`
    on the weekly differences, under `PromotionPolicy()` from `src/squadopt/evaluation/promotion.py`,
    with candidate ids `planner_policy_chain_v1:A` and `planner_policy_chain_v1:B`. No interval is
    printed with fewer than six scored weeks.
28. The final verdict for each contrast is the first clause that holds: fewer than 15 scored weeks
    gives `insufficient_evidence`; an upper bound below 0 gives `worse`; a lower bound above 0 with a
    mean of at least `PromotionPolicy().min_mean_improvement` gives `better`; anything else gives
    `not_separated`. An interim may record only `worse_interim`, when at least six weeks are scored
    and the upper bound is below 0; otherwise it records no verdict.
29. Each reading reports the minimum detectable effect at its own week count from the observed
    standard deviation, by `detectable_effect` in `src/squadopt/evaluation/live_series.py` under
    `DetectionPolicy(confidence_level=0.90, power=0.80)`. No clause depends on it.
30. No verdict switches anything. A `worse` result is reported on #632; whether the routed planner
    stays, and whether its stated limit cites the record, is the owner's decision, made in the
    owner's own pull requests.

## 9. Separation from the football protocol

31. The chain has no current-model arm, no free squad selection, no difference between the football
    and current models and no per-player forecast error. It therefore computes none of the
    quantities `docs/football_prospective_prereg.md` reads, and its readings fall on that protocol's
    reading weeks. Interim records carry paired differences only; each arm's absolute totals appear
    only at `gw38`. No chain reading may be used to withdraw, change or re-time the football option.

## 10. Records and operation

32. The evidence (input receipts, forecast copies, each arm's decision records and the weekly
    manifests) stays uncommitted in the run's output directory. Each reading commits
    `docs/research/planner_policy_chain_gwNN.json` and its markdown twin, rendered from the JSON,
    with a row in `docs/measurements_index.md`. The scorer is `scripts/score_planner_policy_chain.py`.
33. Records name no member, entry or league, hold no news text and set
    `locked_holdout_accessed: false`. The chain reads no archive.
34. The decision step runs once after each deadline, as one heavy job at a time, never on a Tuesday
    or Friday and never during a weekly run or a rehearsal. It never touches the backend, port
    8000, the repository's `data/` or a live store. Who runs it, and on which machine, is settled on
    #632 (Question PC1) before the first chain week.

## 11. What this does not claim

The chain uses constructed squads, not members' squads, over one season. A difference between arms
is a difference between these policies on these squads under the served forecast. It is not a
forecast of any member's result and not evidence about any other planner. It does not test chip
timing, the Top 100 weight, the manager's word or the preferences.
