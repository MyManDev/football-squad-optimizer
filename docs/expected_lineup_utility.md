# Expected lineup utility and conditional planning

The complete frozen-capture comparison is in [expected_lineup_measurement.md](expected_lineup_measurement.md), with all 42 records summarized in the adjacent JSON. No improvement in realized scores or prediction calibration is claimed.

Weekly XI rotation already existed. This change evaluates complete three- and five-week plans with explicit vice-captain and bench decisions, expected automatic substitutions and captain fallback. Final ranking has no fixed bench bonus.

## Activation limits

One-week pure-points advice from the fixture-football candidate now retains the published weekly appearance probabilities and improves roles on the native transfer proposal. The nominal multiweek expected-lineup route is enabled for the fixture-football model over three or five weeks, with appearance probabilities present and an explicit deterministic solver budget of at least five. Automatic chip strategy must be off, and first-week overlap, transfer-cap and role-exclusion arguments must all be absent. Existing alternative routes retain their prior behavior; the new autosub objective does not apply to every product combination.

The public `model=football` selector uses the currently accepted football artifact; it is not a joint-role-only route. The reader accepts team-share v1, contextual v3, joint-role-minutes v1 and its explicitly selected retained-history variant under the same fixture-football family. Joint-role inputs additionally require their complete ready bundle. A usable observed-information node takes precedence and goes directly to the observed planner. The optional nominal proposal below therefore does not extend the observed action menu. Current-model and overlap-constrained solves retain their existing routes.

Top100 remains a user choice. Nonzero-weight pure-points football requests keep one selected-weight planning call and rescore its decisions on the raw forecast for publication. This proposal neither adds a zero-weight solve nor interprets preference utility as raw FPL points.

Keep, avoid, no-hits and save-chips preferences remain supported through the certified resource path. The role helper itself also supports starter and captain/vice exclusions, but this does not change the live routing limits above. Forced-chip scoring and state preservation are tested separately; those tests do not establish activation for every chip product route.

The retained-history role variant is an explicit operator choice: add `--retained-role-history` to `build_football_forecast --role-minutes --with-components`, with the same complete explicit training-season selection. Omitting the new flag keeps the previous model. Its separately identified artifact and matching companion still require a complete ready bundle; existing immutable artifacts are never replaced by that command. This adds no member-facing model selector, automatic promotion or new probability display. The retained-history feature changes only the conditional role head, and remains development evidence rather than independently verified predictive superiority.

## Scoring mathematics

For player i, mu_i is unconditional expected gameweek points and q_i is the probability of any appearance that gameweek. Appearance is already included in mu_i and is not multiplied again. Inputs must be finite, q_i must lie in [0, 1], and q_i = 0 requires mu_i = 0. The pure evaluator accepts signed points.

For legal XI S, ordered bench B, captain c, vice v and actual transfer charge H:

    E[net] = sum(mu_i for i in S)
           + sum(a_i * mu_i for i in B)
           + k * (mu_c + (1 - q_c) * mu_v) - H

Here a_i is the probability of admission as a substitute conditional on that player appearing. It excludes the incoming player's own q, which is already in mu. The captain bonus multiplier k is 1 normally and 2 under Triple Captain. Captain and vice both start.

The evaluator convolves missing starters by outfield position and considers eight appearance patterns for the three outfield substitutes. It applies bench priority and legal formation, requiring at most 640 combined states per lineup. Goalkeeper replacement is separate: the reserve's coefficient is 1 - q_starting_goalkeeper. Captain fallback is analytic. No Monte Carlo draws are used.

Any cameo blocks replacement. For double gameweeks, the caller supplies the probability of at least one appearance and total gameweek points. Bench Boost counts all fifteen players' unconditional points plus captain fallback, with no separate autosub addition. Triple Captain also applies its extra multiplier to the playing vice when the captain misses the whole gameweek.

The expectation is exact under independent Bernoulli player appearances and conditional point means unaffected by other players' appearances, using the existing official scorer's substitution semantics. Correlated absences, point dependencies and card-only participation without minutes remain outside this model. These assumptions are recorded.

With roles and q fixed, the total is linear in mu. Recorded player multipliers allow an exact conversion from Top100-weighted points to raw points without changing the selected XI, captain, vice or bench order and without another solve.

## Bounded search and decisions

Each weekly role-search invocation retains its incumbent and evaluates at most 128 distinct lineups by default. Candidates use legal one-for-one XI swaps within the same fifteen and six outfield bench orders. The incumbent XI receives its complete bench-order pass before neighboring XIs are explored round-robin, subject to the unchanged total cap. A cap below seven can stop that pass; the ordinary 128-evaluation call covers it. Every eligible ordered captain and vice pair in each explored XI is ranked analytically, at most 110 pairs. Pair ranking requires no additional full lineup scores or autosub calculations; those results remain cached. Evaluation counts, actual convolution states, captain pairs and cache use are recorded. This is a bounded search, not a global optimality proof. Branches can invoke it repeatedly, so 128 is not the request-wide budget.

The frozen 42-record comparison below predates this complete captain-pair search and was not rerun for that change. Its new validation uses controlled fixed-XI cases and an independent official-outcome scorer; it does not establish realized score gains.

CP remains responsible for feasible transfer, price, bank, free-transfer and chip paths. Its bench-weighted objective is a proposal surrogate. Ordinary expected-window planning allocates 40% of its solver budget to a guarded legacy proposal and 60% to a guarded zero-bench-bonus proposal, then ranks complete candidates on the common expectation. Observed planning retains a guarded baseline and budgets hold/information proposals, continuations and reconciliation together. Solver work and lineup evaluation work are reported separately.

### Optional initial-squad swap

The nominal expected-window route retains both original complete proposals and their 128 role evaluations per week. Only after both native solves are optimal for their surrogate, their seeds are complete and no wall-clock truncation occurred can one additional proposal use the deterministic CP budget that was actually unspent. The optional primary solve and tie-break split the remaining wall allowance. Issued allocation, released/reused allocation and actual work are reported separately.

A deterministic same-position scan considers at most `15 * (N - 15)` initial-roster replacements, where N is the first-week player-pool size. Expected-lineup multipliers provide a cheap ranking heuristic, not a certified gain. At most one template score and one cold full-horizon CP call are added. That call keeps the original purchase lots, bank, free transfers, prices, dated chip rights, preferences and transfer policy. It fixes only the proposed first squad; subsequent weeks remain free to transfer, including reversing that choice. An all-weeks-fixed witness is consequently not an oracle for this completion.

Unsupported horizons, first-week Wildcard/Free Hit, role exclusions, insufficient solver slack, duplicate first squads and absence of a positive legal pair leave the original menu unchanged. An incomplete, infeasible or wall-truncated optional solve also leaves it unchanged, while its spent work remains counted. Equal final utility retains the earlier proposal. Native resource certification does not prove optimality for the expected-lineup objective.

The exact lineup-evaluation allowance deliberately increases from `256 * weeks` to `384 * weeks + 1`: 1,153 for three weeks and 1,921 for five. The original two searches are unchanged; the additional allowance is one template evaluation plus at most 128 per new-candidate week. CP work, exact evaluations, convolution states and elapsed time must be compared separately. This is not an equal-total-work or predictive-improvement claim. The earlier 42-record comparison below predates this optional proposal and is not evidence for its effect.

Role improvement preserves every resource decision and purchase history. Explicit starter exclusions are respected; captain exclusions also constrain the vice. Other human constraints remain in the certified resource path.

Before information arrives, the full first action is frozen: squad, XI, captain, vice, ordered bench, transfers and chip. Reused full-horizon decisions are independently certified against current inputs. Future decisions may react to the declared nodes. Every admitted first action needs complete continuations under both nodes before comparison. Incomplete comparison retains the complete baseline; a one-action menu is reported as having no distinct alternative.

Published net points deduct actual transfer charges. Selection may use a different declared hit cost: for n paid transfers and selection cost h, utility is E[net] + H - n*h. Ordinary expected-window selection can also include configured discount and terminal values. The current observed comparison uses no discount and zero terminal values. CP bounds do not certify the new expected objective or its restricted action menu.

## Participation evidence

A captured percentage represents eligibility, not starting or appearance probability. Given original eligibility e and appearance q, replacing eligibility gives q_new = (q/e)*e_new. For positive q, mu_new = (mu/q)*q_new preserves conditional points. A zero basis cannot be inverted without an explicit conditional point forecast.

Captured percentages are checked against the original forecast as a no-op, avoiding a second availability penalty. Cited, timely expected-absence statements may set first-week appearance and points to zero. Rotation warnings, broad minutes comments and confidence labels receive no invented probabilities; unsupported statements remain unapplied with reasons. The generic adapter accepts separately documented assumptions or external calibration, but this news integration supplies no external calibration. A separate explicit full-match restriction can revise minutes only from a verified fixture-component basis as described below; it does not refit starting probability.

Evidence is tied to its source, season, gameweek and deadline. No recovery date is invented. Later-week zeros inherited from older forecasts remain when a conditional forecast is unavailable, and this limit is disclosed. The separate information experiment resolves one held player's captured eligibility before the next deadline while preserving mean forecasts. That timing is a scenario assumption, not a measured recovery prediction.

## Explicit coach constraints and model configuration

The existing registered club-news acquisition, citation locator and rotation exporter are reused. A model may identify a current upcoming league match statement that a player cannot complete a full match. A deterministic source-quote gate rejects uncertain, conditional, past or unspecified-match wording for the new label. The exact stored UTF-8 citation span, source digest, publication/fetch time, decision cutoff and deadline remain necessary. Vague managed-minute language does not trigger this intervention.

A full-match restriction removes the 90+ minute class and reallocates its mass proportionally between the already learned positive shorter classes. The zero-minute probability is unchanged. This is an explicit intervention assumption, not a calibrated Bayesian likelihood of a coach statement. Missing shorter support, zero effective appearance, conflicting or repeated sources and ambiguous multiple-fixture scope are refused. A separately valid absence takes priority. No forecast is recovered from an unavailable conditional basis.

The optional sibling fixture companion must bind the exact served forecast, source capture, training identities, complete player roster, captured calendar and unapplied availability header. Runtime advice consumes the versioned JSON contract from #912 without retraining. The separate forecast builder can now opt into publishing that companion from the same fit as its forecast; see [club_news_configuration.md](club_news_configuration.md). The current artifact alone cannot reconstruct the missing component detail. Without this companion the original football forecast remains usable and the minute statement is reported unapplied.

For affected club-fixtures, the component consumer recalculates minutes, 60-minute credit, clean-sheet and defensive-contribution terms, the existing residual and attacking allocation. New attacking weights are old share times new minutes divided by old minutes, normalized over the full club. Original credited team goals and assists are preserved. Affected teammates are updated too. Weekly eligibility is applied once to the sum of fixture points; weekly appearance is eligibility times one minus the product of fixture absence probabilities. Future weeks and unaffected clubs remain unchanged. This retains the v1 residual model rather than claiming a new card, save or bonus model.

The operator selects OpenAI or an OpenAI-compatible endpoint, model and private key without changing source code. See [club_news_configuration.md](club_news_configuration.md). The acquisition process makes the model call before the decision capture. Each advice request consumes the immutable result. An offline settings check does not authenticate or make a paid request. Requested and returned model, prompt version/hash, endpoint hash, output format and token ceiling are recorded without the secret or raw private endpoint. New responses must match the requested coding version; old V1 captures remain readable with the original prompt identity. No automatic retry, model/provider switch or format downgrade is used.

API configuration is separate from source coverage. At the time of the frozen comparison below, the real registry covered Liverpool and Newcastle, plus a placeholder. The subsequent 1 October news integration added Crystal Palace and verified one real Gemini response with zero usable player claims. These later checks are not part of the 42-run comparison. A key alone does not add the other clubs; the dated coverage record is in [club_news_sources.md](club_news_sources.md). No current production companion, held-out model fit or news-effect calibration was produced by those checks.

## Complete comparison and limits

The fixed matrix compares legacy bench weight 0.1, zero bench weight and expected-lineup selection for both 3 and 5 weeks and Top100 weights 0, 5, 10, 20, 30, 40 and 50. Every version is rescored on the same raw forecast and official expected-lineup basis. Legacy unspecified roles are completed by the declared publication rule; expected policies retain their explicit roles. Conditional scores use each declared node's raw conditional points and appearance probabilities. All 42 request outcomes fit the configured solver and latency budgets. Independent replay passed all 42 saved resource/score paths; it reused the exact scorer while reconstructing transitions and branch forecasts independently.

Raw nominal expected points exceed legacy in 11 of 14 matched settings and fall below it in 3. Against zero bonus, the result is 7 higher and 7 lower. Conditional raw points are mixed too. The common Top100 selection utility is higher than legacy in all 14 nominal settings and in 13 conditional settings with one tie, but these preference units are not FPL points. Overlapping settings are descriptive comparisons, not independent samples or realized accuracy evidence. No parameters were selected from the winning cells.

There is no applicable cited news artifact in this frozen capture, so its no-evidence news result is unchanged and is not solved a fourth time. The additional news path is exercised with controlled synthetic, source-cited records. That comparison did not verify model authentication, all-club coverage, a current production companion, news calibration or realized point gain. The later successful Gemini call verifies authentication and inference only; it does not revise the comparison or establish a numerical news effect.


## Fixture and availability decisions in the one-week candidate

The owner's 9 October 2026 request extends the experimental one-week football plan,
not the forecast fit. It uses the same fixture-level point expectations and effective
weekly appearance inputs already carried by the accepted football artifact. No current
season outcome is read, no capture is rebuilt and no forecast or model version is
replaced by this implementation. This is decision arithmetic and synthetic validation,
not a claim of realized improvement. The prospective reading retains its declared
GW20/GW38 schedule and records the planner revision it uses.

### Research and code trace

The current [official FPL rules](https://www.premierleague.com/en/news/4661029)
specify priority-order automatic substitutions, separate goalkeeper cover, formation
constraints and captain-to-vice fallback. A short playing appearance prevents an
automatic replacement; an injury flag alone does not determine the decision.
The scorer uses weekly positive-minute appearance. Card-only participation remains the
explicit unsupported case stated in the existing assumptions above.

[Dixon and Coles, 1997](https://rss.onlinelibrary.wiley.com/doi/abs/10.1111/1467-9876.00065)
develop a Poisson regression model for football scores with changing team performance.
This supports modeling fixture context upstream; it does not establish that this
repository's forecast or lineup choice is calibrated.
[Venter and van Vuuren, 2024](https://orion.journals.ac.za/pub/article/download/753/648/1931),
section 5.4, select captain and vice by predicted points and order substitutes by
forecast performance. That is a useful deterministic comparison, not evidence for
our appearance-conditioned extension. Its historical rules and retrospective result
are not used as current FPL rules or as a promotion gate.

In this repository, `prediction/football_features.py` attaches recent own and opposing
club goals and xG strengths plus venue to each fixture. `prediction/football.py`
predicts own goals and conceded goals, then player goal/assist shares and clean-sheet
credit. `football_contextual.py` additionally consumes opponent-adjusted dynamic
strength. The planner therefore receives the effect of the player's club and opponent
inside mu. A second club-strength or opponent multiplier in bench ordering would
count that context twice.

The artifact reader's availability rule scales both unconditional mu and learned q
once. A source 75 percent is an eligibility multiplier, not a newly calibrated
75 percent starting or appearance prediction. The participation adapter audits the
same capture percentage as a no-op. This implementation copies effective q into the
one-week planning horizon without reapplying the source percentage or fitting a new
participation model. Missing q is refused on explicit expected-lineup calls; it is
never replaced by certainty.

### Joint first eleven and ordered reserves

The native one-week planner first supplies a feasible purchase, transfer and resource
path. Its selected fifteen remain fixed during role search. The role scorer evaluates
legal first elevens, the six outfield reserve orders and captain/vice choices using
the expectation above. XI alternatives are legal one-player swaps; after the incumbent
bench pass, their orders receive round-robin turns up to the unchanged cap of 128.
This can change a flagged starter, the starting goalkeeper, captain, vice and reserve
priority. It does not globally optimize all squads or every possible eleven.

Consider a synthetic defender with q = 0.75 and conditional points 6, so mu = 4.5.
A certain replacement defender has mu = 5. With no other uncertainty or formation
conflict, starting the flagged defender with this cover scores 4.5 + 0.25 * 5 = 5.75,
whereas starting the replacement scores 5. Flagging the player therefore does not
justify benching him. If his conditional expectation becomes 2, mu becomes 1.5:
starting him scores 1.5 + 0.25 * 5 = 2.75, so the replacement should start. These are
fabricated arithmetic examples, not estimates for any named player.

The reserve decision also depends on the XI's formation. With three starting
defenders, a missing defender may require defensive cover even when a midfielder has
more forecast points. With four defenders, a forward or midfielder may be eligible.
A fixture-driven change to that reserve forward's mu can therefore change the optimal
first reserve. Any cameo blocks the replacement; starting probability is not used
as a substitute for appearance probability. Double gameweeks retain the caller's
probability of at least one appearance over the whole week.

### Accounting, controls and validation

Only experimental fixture-football member controls enable the new one-week role path;
the low-level `plan_transfers` flag defaults to false. Current-model, proven-menu and
rival-band callers retain their prior entry points. The separate active-preference
menu retains its existing routing; this extension does not claim every product
combination uses the new one-week roles. An explicitly forced chip on the
experimental control uses the same role expectation, so its value and the no-chip
control share one scoring basis; chip and reserve points are counted once. Manager exclusions
on the experimental control pass their starter and captain restrictions to role
search, including the vice. Top100 chooses on weighted mu and publishes the same
frozen roles on raw mu through the exact player multipliers. Price comparisons use
that same expected-score basis, and bench/vice changes count as changed decisions.

The native CP objective remains a proposal surrogate. Role improvement reports
FEASIBLE and clears surrogate bounds; no proof of globally optimal expected points
is invented. It preserves transfers, purchase prices, bank, free transfers and chips.
Legacy held-XI move deltas are withheld for expected-lineup payloads because they do
not include reserve or vice recovery. No extra percentage, caveat or limit sentence
is added to member-facing copy.

The new synthetic cases independently enumerate tiny appearance worlds through the
official realized scorer. They cover both flagged-player decisions, fixture-sensitive
reserve priority, minimum-defender cover, cameos, unchanged q and single application
of participation. A regression fixes starvation of the incumbent's sixth reserve
order at the ordinary cap. Full-action locking and a one-evaluation cap retain the
incumbent. The fake API/queue/worker test also reconstructs each published window-1,
window-3 and window-5 decision on unweighted artifact points, including Top100 and
both v1/contextual inputs. Those tests open no server process and read no real outcome.
