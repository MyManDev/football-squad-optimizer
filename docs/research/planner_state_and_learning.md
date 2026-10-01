# Planner state, observation and continuation contract

The production solver chooses legal plans under supplied forecasts. The existing
observation planner is a two-stage finite-menu rollout, not a complete learned
season policy. The current acquisition correction adds purchase basis for known
in-window acquisitions; it does not predict market prices.

## State and action

A sufficient decision state must include the deadline, permanent squad, per-player
purchase lots, bank, banked free transfers, dated unused chip rights, scoring/rule
version and locked user preferences. The information state additionally contains
the forecasts, fixture publication times, availability observations and any calibrated
belief over later news. Bank and aggregate squad value alone are insufficient:
two equally valuable squads can have different future sale proceeds and fixtures.
Football health and future coach decisions are partly observed; an approximate
belief state makes this a partially observed control problem.

An action includes incoming/outgoing players, XI, ordered bench, captain/vice captain
and at most one eligible chip. The existing solver supplies the legality mask:
budget, positional/team quotas, unique players, transfer resources, chip periods and
keep/avoid/no-hit/save-chip preferences. A learned score may rank valid actions; it
cannot relax those constraints. After Free Hit the permanent squad, purchase lots
and bank are restored. Wildcard retains its acquisitions. Chip rights are indexed
by validity period, not simply by whether a chip name was ever used.

## Reward, information and Bellman comparison

For the declared scoring basis, r_t is realized lineup/captain/chip points minus
the actual transfer charge. Historical chains without automatic substitutions
remain labelled with that limitation. Forecast points and Top100 preference utility
are separate quantities. Top100 is a user-controlled objective, not a learned
forecast correction or realized reward.

V_t(s,I) = max over legal a of E[r_t + gamma V_(t+1)(T(s,a,O),I+O) | I].

The implemented two-stage approximation evaluates the SAME first action in every
next-deadline information branch. Maximizing independently inside each branch
before selecting today's action would grant perfect future information. Synthetic
news stresses with assigned probabilities test sensitivity; they do not establish
calibrated injury or rotation probabilities.

Every rolling arm receives the same information available at that deadline,
applies only its first action, carries its own wallet/resources and then replans.
Report transfer counts, reversals, paid transfers and net points separately. A
forecast change is not permission to reset a squad, use future news, or erase hits.

## Continuation and proof limits

An explicit tail forecast already counts its future points; do not add a second
learned value for those same weeks. A learned terminal value can begin only AFTER
the explicit horizon, on the resulting state. Resource bonuses and chip reserves
must not also count rewards already represented by that value. A paired extra-FT
value is a difference of proved continuation optima; two feasible lower bounds do
not identify it. Restricted-menu or restricted-neighborhood optimality is not global
policy optimality. Consistent exact policy evaluation is required for the usual
rollout improvement argument; changing beliefs and bounded solves weaken it.

The existing dated single-chip benchmark solves V(t)=max(gain(t),V(t+1)) on a
fixed squad and explicit calendar. It is an exact restricted stopping reference,
not a general transferable chip-value model. Multiple chips can compete for the
same week, and transfers change the bench and captain opportunity.

## What this night's archive can support

The audited 24 files contain 80 historical chains and 2940 recorded decisions.
They lack complete purchase lots, exact XI/captain actions and timestamped modern
football-model observations. Repeated policy variants share football outcomes.
The continuation diagnostic therefore predicts a recorded policy's next 3/5-week
mean net return from six coarse decision-time features. It is not a fitted-Q target
or a Markov value function, and cannot select a better live action by itself.

IQL or CQL cannot reconstruct missing observations or validate unsupported action
values. Their implementation/promotion is deferred on this archive. The existing
legal-menu rollout remains the usable planning approximation, with explicit
unknown-state fallback. A future policy experiment needs immutable per-deadline
forecasts and their publication times, permanent lots/resources, complete selected
and alternative actions, later observations and settled player outcomes under one
scoring contract. Collection should extend the existing immutable evidence boundary,
not create a second service or use the live queue as a learning environment.

No new independent realized-outcome holdout is available in these files. The final
night-plan promotion gate cannot be passed by a lower development MAE, larger
predicted utility or synthetic Bellman test. Those results remain useful separately.

An independent small Bellman test now enumerates all 16 legal first squads for
three and five weeks. It carries free transfers and actual hit charges through
each subsequent decision, observes one of two posterior forecasts only after the
first action, and compares every candidate value with the existing CP rollout.
Both exact checks pass. Equal prices, four-player squads, no chips and synthetic
information probabilities bound this result; it is not season-policy evidence.
