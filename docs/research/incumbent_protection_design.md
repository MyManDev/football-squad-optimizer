# Certified incumbent protection for explicit lookahead

This opt-in decision-core change addresses bounded search that returns a worse path
than a known complete feasible plan, or no path at all. It is not a new point model.
Served callers do not enable it by default.

## State and comparison

The state before a deadline comprises permanent squad identifiers, bank in tenths,
free transfers, known acquisition prices for purchases made on this path, and dated
chip rights. Original holdings use the supplied sale-price paths because their
purchase prices are not inferred. Free Hit restores the entering permanent squad,
bank and purchase lots; its free-transfer transition follows the configured rule.
Wildcard purchases are permanent. Consuming one chip period does not consume a
later period's right. A forced future chip cannot be spent by an earlier segment.

Both paths must use the same forecast rows, starting state, rules, available rights,
user preferences and objective configuration. Top100 weighting is already part of
the supplied forecast; this code neither selects the weight nor changes it.
Keep/avoid/no-hit/save-chip constraints apply to every forecast week.

A path's decision objective is the discounted sum of starting-player points,
captain bonus, configured bench value and configured transfer penalty. Reported
game hit points remain distinct from a possibly larger optimization penalty.
The solver rounds coefficients to its integer scale. Protection compares that
integer objective, so it promises no regression on the *scaled model objective*,
not strict monotonicity of every unrounded reported metric. Raw forecast points,
weighted utility and realized points must not be conflated.

## Certification and fallback

`optimize_transfer_plan(..., incumbent_plan=plan, protect_incumbent=True)`
fixes supplied decisions and resource transitions in a clone of the current full
model. The clone keeps all present constraints but has no objective. Its feasible
witness supplies hints and its objective is recomputed from current model variables.
Neither a supplied score nor an OPTIMAL label is trusted. Mismatched horizon/rule
fingerprints, incomplete weeks, invalid roles and inconsistent resource transitions
are refused. A failure to certify is an error, not permission to reuse the plan.

If unrestricted search is UNKNOWN or returns a lower feasible scaled objective,
the certified witness is extracted through normal independent bank/FT/purchase
accounting. It is labelled FEASIBLE, with no inherited global bound or gap.
An INFEASIBLE full search, or a purported OPTIMAL result below its known witness,
is an internal contradiction and raises. A better result is accepted normally.

The existing hint-only mode keeps its previous behavior. Incumbent and hold
protection are mutually exclusive. `optimize_with_lookahead` chooses incumbent
protection only when a full incumbent is explicitly supplied; otherwise it retains
the existing hold protection.

## Complete paths from segments

`plan_in_segments` uses the existing solver to build sequential one-week or
window-then-tail paths on the original decision-time forecast. It rebases sale
prices from permanent purchase lots at each boundary, carries bank/FT/dated rights,
preserves full squad/XI/bench/captain and transfer decisions, and joins only complete
feasible segments. Contributions use the original horizon discount clock.

The supplied explicit deterministic cap covers all segments, apportioned by
segment length. No hidden hold probe is added. Segment runtime and statuses are
recorded; a failed segment raises instead of returning a successful prefix.
The result is FEASIBLE with segmented proof scope. Its full-model certification
must still be charged before it is selected against another search. Construction,
certification and unrestricted search all belong in the end-to-end study budget.
A nominal cap is not exact work: actual solver counters and wall stops must be
reported, including bounded overshoot.

Terminal FT bonuses and chip holding values are refused here and in explicit
lookahead: their use at each artificial boundary or alongside an explicit tail
would count continuation resources twice. The displayed decision window remains
three or five weeks; additional forecast weeks inform continuation and are reported
separately.

## Mathematical and evidence limits

This is deterministic optimization on one information set. A sequential one-week
path repeatedly optimizes the unchanged forecast; it is not a backtest with new
information arriving each week. A long solve has perfect access to the *forecast*,
not perfect knowledge of future outcomes. An MDP extension must choose the first
action before future observations and condition later actions only on observations
then available. No learned policy, calibrated transition probabilities, new data or
future-performance guarantee is introduced.

Synthetic tests cover forced deadlines, chip renewal, Free Hit restoration,
acquisition fees and repurchases, preferences, budget exhaustion and lying score/
proof metadata. Small three/five-week problems are checked against exhaustive
independent enumeration. These establish correctness on stated cases; real-data
quality measurement and full application/browser integration remain separate gates.

