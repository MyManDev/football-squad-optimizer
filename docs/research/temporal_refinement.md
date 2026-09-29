# Temporal repair for bounded three- and five-week planning

The previous observed-rollout experiment produced thirteen unchanged menu values in
fourteen constructed cases. Its five-week solutions were feasible, without a proof
of optimality. This experiment addresses search quality within the same forecast,
instead of fitting another terminal bonus to that capture.

## Mathematical contract

Let F contain every full-horizon feasible plan under the supplied initial squad,
bank, free transfers, prices, chip rights and human preferences. Let J be the
existing discounted objective, including the configured bench and resource terms.
Given incumbent x and adjacent gameweeks B, define

    N_B(x) = { y in F : squad_t(y) = squad_t(x) for every t outside B }.
    x_next = argmax { J(x), J(y) }, for a complete feasible candidate y in N_B(x).

All players remain eligible inside B. XI, captain, bank, FT and chip decisions are
solved over the original horizon. No boundary bank or FT is reset, and a Free Hit
retains the original model's squad/bank restoration. Thus x belongs to N_B(x).
UNKNOWN retains x; an INFEASIBLE neighborhood contradicts that incumbent and raises
an error. Accepted improvements must increase the same unrounded objective by more
than numerical tolerance. This proves incumbent non-regression for the supplied
model, not higher realized FPL returns or a globally optimal MDP policy.

The opt-in wrapper makes one chronological sweep of adjacent pairs. It skips repair
when the unrestricted baseline has already proved its scaled integer objective.
A restricted solve's OPTIMAL status and bound apply only to that neighborhood;
the wrapper exposes its own proof scope rather than upgrading the whole plan.
Prices retain the existing supplied-price approximation; future purchase-lot paths
and uncertain information transitions are not newly solved here.

This uses the decomposition principle in
[Song et al., NeurIPS 2020](https://papers.nips.cc/paper_files/paper/2020/file/e769e03a9d329b2e864b4bf4ff54ff39-Paper.pdf),
with fixed time neighborhoods rather than a learned selector. CP-SAT already contains
its own search machinery; this application-level experiment must beat the direct
solver, not assume it does. See the
[official solver notes](https://github.com/google/or-tools/blob/stable/ortools/sat/docs/troubleshooting.md).

## Measurement protocol

Reuse the immutable GW6 capture and lagged Top100 evidence from the previous matrix.
Constructed profiles 1000 and 900, windows 3 and 5, and user weights 0, 20 and 50 make
twelve cells. Four additional five-week, weight-20 cells cover keep/no-hit/save-chip
preferences (with TC and BB available to save) and a forced first-week Free Hit for
each profile. No owner holdings,
future outcomes, trained parameters or new forecast identities are used.

The incumbent uses 120 wall seconds and 60 deterministic units. Each repair has
30 wall seconds and 15 deterministic units. The direct control receives their summed
caps in one unrestricted solve. Both initial searches retain the existing hold
probe; repairs use the incumbent fallback. Alternate arm order by cell. These are
equal configured caps, not identical actual CPU consumption: early proofs and the
solver's tie-breaking phase are recorded in diagnostics and actual elapsed times.

Report every case and failed attempt, restricted status, acceptance history,
independently rescored raw points, preference utility and hit cost. The engineering
screen requires sixteen valid pairs, no incumbent regression, at least one utility
gain over 0.1 against the control, and no utility loss worse than 0.1. It is not a
promotion gate for forecast accuracy or future season return. No Top100 weight is
automatically chosen for the user. Changing that preference changes the objective,
so a higher weighted score with lower raw points is an explicit tradeoff.

The protocol was recorded before this run. This is a repeated development capture,
not new independent evidence. Bayesian tuning on it would optimize the same spent
objective; it is not added. No website or backend default is changed by this module.
