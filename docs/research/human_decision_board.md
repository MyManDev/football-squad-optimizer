# Human decisions over computed FPL alternatives

22 September 2026. Follow-up to the [component and planning study](football_component_ablation.md).

## Decision framework

The [official FPL expert retrospective](https://www.premierleague.com/en/news/4322002)
emphasises secure minutes, patience, preserving free transfers, weighing hits and looking
beyond one week. Experts also disagree about when an early Wildcard or a shorter-term pick
is justified. This motivates exposing alternatives and their assumptions rather than
installing a single supposed expert policy.

[Fantasy Football Fix's own Top 50 analysis](https://www.fantasyfootballfix.com/blog-index/fpl-top-50-tips-transfers-2026-27/)
reports a preference for later transfers and interpreting fixtures, role and minutes rather
than simply chasing last week's score. These are descriptive observations of selected
successful managers, subject to selection and survivorship bias; they do not establish the
causal value of copying their choices or adjusting a player's predicted points.

Our product inference is to let the human compare an explicit, small set of computed
alternatives, record why they prefer one, and revisit the decision when information changes.
No new model coefficient or automatic transfer policy is inferred from the articles.

## Implemented scope

The member page now has a bilingual, mobile decision board below the main advice. Users
pin up to three completed plans generated using the existing model, 1/3/5-week horizon,
Top100, manager-news, rival and chip controls. Unsupported combinations remain governed by
the existing capability checks. The board does not start jobs, submit FPL transfers or
activate chips. Opening a saved plan restores its URL settings; computation still requires
the existing explicit action and deadline checks.

Each card shows first-week expected points net of hits, first-week net gain against holding,
full-horizon net points and hits where all consecutive weeks are present, remaining transfer
rights where stated, captain, chip, transfers, solver status and bound gap. Missing evidence
is a dash, never a made-up zero. FEASIBLE is a valid incumbent, not a proof of optimality;
OPTIMAL is conditional on the model and constraints, not a guarantee of football outcomes.
Negative first-week net gain has an explicit note to examine the later-week justification.
Different models' point scales and different horizons are not automatically ranked.

Users mark a personal preference and enter a short reason, prompted by minutes, fixtures,
transfer flexibility, captaincy, chips and missing team news. The reason is a private note,
not a model input, training label or claim that its assumption was measured. Preferences are
kept in browser session storage only. Storage failure is disclosed without losing the current
in-memory selection. No new authentication, database, service or dependency is introduced.

## Context and validation boundaries

Every pinned and restored answer is checked against the selected member, week, strategy,
model, switches, source kind, capture and squad basis. A fallback answer for another selection
cannot be pinned. Unsolved or incomplete lineups cannot be pinned. The saved context includes
the full squad document: a changed roster, bank, transfer rights, source capture or publication
resets the board. Legacy answers lacking a squad-basis claim cannot be compared to a squad
that explicitly declares a basis. Stored notes are rendered as text, never HTML.

Unit coverage checks net-hit accounting, missing/incomplete metrics, stale answers,
switch mismatches, corrupt storage, resource changes, full URL restoration and preference
persistence. Mobile browser tests exercise pinning two horizons, choosing one, retaining a
reason after reload, reopening settings, removal, zero POSTs, overflow and accessibility in
both Turkish and English. These browser tests use declared example fixtures; they are not
live-backend, real-FPL or prediction-accuracy evidence. Full repository gates remain required.

Final local verification: 6,697 Python tests passed, 15 skipped, nine existing GP convergence
warnings; Ruff/format, strict mypy and all three import contracts passed. Web schema, lint,
format, typecheck, build, deployment assets and size gates passed; 1,288 unit tests passed,
two skipped. The full browser suite passed 90 tests with two workers, two service-dependent
scenarios skipped. A pre-existing mobile assertion counted every disclosure as a responsive
context panel; it now selects the two named squad/chip panels, retaining all responsive
assertions. The new decision-board scenarios pass in both languages. Only this documentation
was completed after the final gates. Fresh CI, including isolated API/worker browser
acceptance and container verification, is tracked on the PR separately.

## Deliberately separate follow-ups

The previous study's five-week solver incumbents below a known holding baseline are still a
planner issue; a UI comparison does not repair or certify that solver behaviour. A separate
solver change should seed or preserve a feasible hold alternative and validate timeout
fallbacks. Empirically calibrated injury/minutes observation scenarios and forward policy
evaluation are also still needed before claiming a better MDP policy.

Player locks, user-edited minutes and injury probabilities, additional research component
toggles and server-side decision histories are not implemented by this board. They require
explicit request validation, consistent rescoring and comparable evaluation before becoming
forecast controls. The present change provides the human comparison/choice loop over already
supported alternatives without promoting the unproven contextual model.
