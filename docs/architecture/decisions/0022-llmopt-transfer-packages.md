# ADR 0022: Bounded transfer packages and three-week paths

- Status: accepted
- Date: 2026-11-19
- Decider: project owner
- Related: ADR 0021; PR #1469

## Decision

Ship the package implementation with both `SQUADOPT_BACKEND_TRANSFER_PACKAGES`
and `SQUADOPT_BACKEND_PACKAGE_GATE` set to their default of 0. In the
[full-pool comparison](../../research/llmopt_phase6_results.md), opening the gate
produced 16 package proposals. The planner accepted none. Across the 18 completed
member-weeks, the gains in raw starting-eleven points, expected net squad points
and selection utility were each zero. The two remaining member-weeks had no result.
Both controls stay off until a new measurement demonstrates a gain.

The server also requires the planning release setting from ADR 0024. With it
off, the package controls have no effect on a new calculation. Enabling the
release setting alone retains the original transfer search.

Three-week paths, including the delayed buy, have their own default-off
`SQUADOPT_BACKEND_THREE_WEEK_PATHS` control. With the planning release enabled,
the league and public capabilities can advertise `three_week_paths` independently
of package search and its optional gate. The page reads current capabilities at
confirmation and again on reload. Follow-up submissions use that page's current
grant. If a restored session lacks the path grant, it can still poll previously
started jobs and read saved answers. It cannot start another path. Path visibility
does not change the calculation identity, the search policy, or the four-job
and 488-unit limits. Both package controls remain at their zero defaults.

If optional package work overruns its allowance after a complete incumbent has
been checked, return that incumbent and retain the actual recorded work. An
overrun cannot admit another solve or increase any limit or tolerance. The
three-week page keeps opening-decision groups stable as results arrive. A plain
roll remains available when a mandatory or frozen rule rules out a delayed buy.

Keep both retained expected-window routes and their 40/60 allocation unchanged.
Add optional one/two-transfer packages behind a disabled control. A separate
disabled gate control permits the optional phase after an incomplete proof only
when a retained feasible full path and actual remaining work exist. Measure
packages with the old gate separately from packages with the gate opened.
Neither control changes a disabled configuration's fingerprint or result shape.
Do not change the existing deterministic accounting tolerance or the original
phase boundaries to make the experiment pass.

Rank all single moves from the full player universe. Include the best point
proxies and funding moves in a bounded 32-move pair shortlist. A negative
individual point proxy may fund a useful pair. Check distinct outgoing/incoming
players, positions, club counts, held rules, exact buys, budget, hit and transfer
caps on the complete package. The proxy is not a measured gain or an exhaustive
package optimum. Validate the selected first squad with the full horizon model
and the original initial resource state. At most one optional solver call uses
the existing actual slack and lineup evaluation cap.

Retain the entire existing algorithm, including its optional single, as the incumbent.
Only unused CP work and lineup evaluations may fund an additional package. Reserve
one deterministic unit inside the optional solver limit for stopping granularity;
the accounting cap and tolerance remain unchanged. Select a package only when
selection utility strictly improves and none of the three reported metrics declines,
including the existing terminal resource values in selection utility.
Report raw named-eleven points, expected lineup net points, and selection utility
separately. Do not use realized points. Disclose rejected proposals and their component differences too. This conservative
acceptance rule can reject an expected-net improvement when raw eleven points fall. Keep error rows as errors; missing values
must not become zero gains or disappear from the twenty-member population.

Only effective package-search settings enter the calculation configuration
identity. No deployment setting is changed in this PR.
The page receives the enabled capability and pins its path mode at confirmation.
Three-week paths start after the main plan, use at most two existing alternative
slots, and retain ADR 0018's four-job and 488-unit limits. A delayed-buy path holds
the first deadline and requests the main plan's incoming players in week two;
incompatible mandatory or frozen rules suppress that path. Other hard rules remain
on every request. The second path keeps more opening budget when possible.

Path identity covers all weeks and chips, using ADR 0021's content identity.
Distinct later paths with the same opening transfer/chip decision are grouped
together. The disabled page path retains the existing request behavior. Priority
or scenario runs do not acquire extra automatic jobs.

## Validation

Replay the same twenty frozen Phase 1 member-weeks on the full pool, with the
same budgets, in disabled, pairs-only and opened-gate arms. Run measurements
separately from tests. Test disabled identity/behavior, incumbent retention,
funding pairs, full resource validation, mandatory/frozen rules, path grouping,
confirmation reload and bounded job admission.

The local comparison shares the unchanged retained prefix across its three arms.
Each arm inherits the full prefix work ledger and elapsed time before its own
continuation. This avoids repeating an identical deterministic calculation; the
reported arm work includes the prefix in full. These are algorithm comparisons,
not independent cold-request latency measurements.

Before an optional solve, reserve room for its whole remaining CP allocation plus
one certificate/stop unit and cap the native phase's wall reservation to the
remaining whole units. An initial four-member probe at producer 404ad2168 showed
122.000059 and 122.071752 charged units on two opened-gate continuations. The new
phase must avoid starting that overcommitted work; no tolerance is widened and
no prior phase or frozen baseline record is changed.
