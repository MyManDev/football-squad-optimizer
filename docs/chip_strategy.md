# Chip timing in member advice

The member can hold every chip, force one held chip this week, or ask the joint
transfer planner to choose a chip schedule. Automatic strategy is opt-in. It works
with the selected current/football forecast, 1/3/5-week windows and supported Top100
weights. Named chips in longer windows remain instructions for **this week only**.
Manager-word/rival variants do not acquire chip support implicitly.

**Status since the 2026-09-25 audit (H3): the automatic strategy is not offered to
members.** The page never shows the Automatic option (`AUTOMATIC_CHIP_OFFERED` in
`web/src/features/league/advice/chipChoice.ts`), a link naming `chip=auto` asks for
the plan without a chip, and the backend refuses `chip="auto"` with
`UNSUPPORTED_ADVICE_REQUEST` before any cache read or job. Hold, a named chip over
1, 3 and 5 weeks, and a named chip with a Top100 setting stay offered: the
capabilities still carry `chips.strategy` for them, and they carry no holding value.
The reason is the tail below: V(n) never exceeds the largest sample, and the samples
are the window's own weeks, so holding can never beat the window's best week. In
the synthetic check in `tests/unit/test_chip_strategy.py`, a Triple Captain or Bench
Boost right with eleven dates left after a three-week window is spent inside it.
It returns when the tail values the captured season calendar (fixture counts,
doubles) instead of the window's weeks. The planner stays in the code for research,
and the same test file carries the expected failure that flips then.

## Decision model

The existing CP-SAT transfer model jointly chooses transfers, squad, eleven,
captain and at most one chip each week. Wildcard changes persist; Free Hit restores
the permanent squad. Triple Captain adds the third captain copy and Bench Boost
counts the bench. Published totals and transfer gains use raw forecast points,
even when Top100 influence changes the selection objective.

Each captured season chip period is an independent resource, used at most once.
A horizon crossing renewal can use the old and new rights separately. Free Hit
cannot occur in consecutive weeks, including across renewal. Unknown or ambiguous
chip history is refused. The rule adapter never invents held rights.

Automatic strategy adds a terminal value for each right still unspent at the end
of the forecast. An expiring right has zero continuation value. For a right with
n eligible dates remaining after the horizon and opportunity samples x:

```
V(0) = 0
V(n) = mean(max(x, V(n-1)))
objective = discounted forecast utility - transfer hits + unused-right values
```

This is the finite-horizon optimal-stopping recursion **under the assumed stationary
empirical opportunity distribution**. It is not a fitted full-season stochastic MDP.
Samples come from a proved-optimal no-chip plan using the selected model: extra
captain points for Triple Captain, the bench contribution omitted by the normal
objective for Bench Boost, and proved one-week rebuild gains for Wildcard/Free Hit.
Rebuild budgets use conservative sell proceeds. Every reference must be OPTIMAL;
an unfinished reference is refused rather than turned into a chip opportunity.
The reference receives three times the final solve's deterministic budget under
the same wall-clock safety ceiling; this is a fixed computation policy, not a
parameter fitted to realized returns.
The joint final solve may be FEASIBLE and publishes its remaining objective gap.

The continuation framework is consistent with terminal-value planning described
in [Bertsekas's MPC discussion](https://web.mit.edu/dimitrib/www/Bertsekas_NMPC_IFAC.pdf).
That reference supports the method, not its empirical performance in FPL.
Season windows follow captured rules; the [2026/27 official chip announcement](https://www.premierleague.com/en/news/4679879/whats-happening-with-fpl-chips-in-202627)
describes the two chip sets.

## What the result means

Only the first week's action is current advice. Later dates are replanned after a
new capture. The UI shows the action, schedule, expiry and holding value; holding
values and solver gaps are selection-utility units, not extra predicted match
points. No unmeasured paired no-chip cost is published. Request identity includes
the strategy version, selected forecast, window, chip choice and Top100 weight.
Cached results cannot silently cross those identities.

The tail assumes a stationary distribution and values rights independently.
Future fixture changes, injury news, transfer opportunities and competition
between chips are not simulated beyond the forecast. Wildcard's longer-lived
benefit beyond that window is unmeasured. A one-week sample produces a constant
reservation value; more tail dates do not manufacture evidence of better chances.
Existing negative/inconclusive chip-induction measurements are not superseded by
this feature. No parameter search on realized returns or old-model calibration is
used. Default no-chip advice and the default prediction model remain unchanged.

## Validation and future evaluation

Unit checks cover exact stopping-tree arithmetic, monotonicity and scaling,
expiry/renewal, historical and planned consecutive Free Hit refusal, forced chips,
and exhaustive enumeration of legal small-instance schedules at multiple reserve
levels. Application checks reconcile raw scoring for automatic and manual chips
with 1/3/5-week windows and Top100 influence. API/worker and browser checks cover
request identity, selection and presentation.

Recorded-capture replays use an isolated store and explicit as-of clock. They
validate execution and arithmetic, **not prospective predictive superiority**.
Closed live deadlines stay closed; replay cache is never copied to production.
Before changing the default, evaluate season policies on chronological held-out
seasons with the same captures, matched budgets and chip inventory, including a
hold/manual baseline, zero-reserve and reserve-sensitivity comparisons. Report
net realized points, use/expiry rates, solver proof gaps and paired uncertainty;
do not choose the reserve multiplier on the held-out outcomes.
