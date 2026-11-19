# ADR 0022: Bounded transfer packages and three-week paths

- Status: proposed
- Date: 2026-11-19
- Decider: project owner
- Related: ADR 0021; PR #1469

## Decision

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

Retain the original candidates. Select an optional result only by the existing
expected-selection utility, including the existing terminal resource values.
Report raw named-eleven points, expected lineup net points, and selection utility
separately. Do not use realized points. A primary-utility improvement does not
claim that every component improved. Keep error rows as errors; missing values
must not become zero gains or disappear from the twenty-member population.

The backend exposes disabled configuration controls; enabled settings enter its
existing configuration identity. No deployment setting is changed in this PR.
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
confirmation reload and bounded job admission. Leave activation to the owner
after reviewing the measured coverage and gains.
