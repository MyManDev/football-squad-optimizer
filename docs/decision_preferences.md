# Human constraints and the multiweek control

The member page supports keep-player, avoid-player, no-hit and save-chip constraints
on pure-points advice, for either forecast model and the selected 1/3/5-week window.
They do not change goal probabilities, expected points or Top100 utility. Keep means
membership of every selected squad, not a guaranteed start or captaincy. Avoid means
absence from every selected squad, including selling an already held player in week
one. No-hit forbids paid transfers throughout the window. Save-chip forbids chip use
throughout it. Limits apply to the captured squad, resources and prices; subsequent
real FPL transfers require a new capture.

Keep and avoid each accept up to fifteen unique positive persistent player codes.
Overlaps, malformed IDs, unknown fields and chip/save conflicts are refused.
Keep requires a currently held player; avoid requires a forecast roster player.
The first version deliberately refuses rival strategies and manager-news combinations.
An infeasible set of constraints is reported as no plan, never relaxed silently.
Automatic chip opportunity rebuilds obey the same human constraints as the final plan.
The existing approximate chip continuation remains experimental, not a measured MDP gain.

`preferences` is a canonical object in the advice POST and a JSON query value on GET.
It participates in the request fingerprint, job specification and cache identity.
An absent or entirely off object preserves legacy identities. The worker verifies
the recorded identity before computation. Results echo the object and
`preferences_scope: all_selected_weeks`; the web client refuses a mismatching answer.
Capabilities must explicitly enable the new controls. Static advice never substitutes
for a constrained request. URL sharing, resumed jobs and the personal decision board
all preserve the constraints. A different member's kept-player selection cannot compute.

Top100 can coexist with these constraints. A constrained plan without a chip reports
`selection_top100_weight`; it does not claim a paired raw-point cost that was not
measured. Published point totals remain on the selected forecast model's scale.

The live horizon adapter preserves the optional v2 `appearance_probability` column
without multiplying expected points by it again. Synthetic 1/3/5-week tests verify
both values survive unchanged, including zero-probability blank weeks.

With hold protection enabled, the planner first clones its complete constrained model
and restricts every week's transfer count to zero. Only a solved, deterministic
control supplies a primary-objective lower bound and complete warm start. A forbidden
or unproved control supplies neither. Main-search UNKNOWN can return the verified
control as FEASIBLE, with no invented proof gap. It never becomes OPTIMAL merely
because the restricted control was proved optimal. Publication still rejects searches
cut by the wall-clock safety limit. The control probe has its own one deterministic
unit / at most thirty second ceiling, recorded separately from the main search.

The guarantee compares the same integer-scaled objective, including discounts, hit
penalties, bench and chip continuation values, under the same constraints. It is not
a promise of more actual football points, nor a promise that the first week alone
beats holding. If no valid control was proved, no dominance claim is made.

The member page separates the decision squad publication and decision gameweek from
the latest scored week/outcome publication. Updating fixtures or outcomes does not
rewrite frozen forecasts. Early upcoming-week plans omit later news and must be
refreshed before the deadline; they are not deadline-day evidence or model promotion.
