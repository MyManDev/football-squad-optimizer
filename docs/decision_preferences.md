# Human constraints and the multiweek control

Pure-points advice supports keep-player, include-player, avoid-player, no-hit,
hold-transfers and save-chip constraints for either forecast model and the selected
1/3/5-week window. They leave forecast inputs and Top100 utility unchanged. Keep and
include require the player on every selected squad. The optimizer still chooses the
starting eleven and captain. Avoid excludes the player from every selected squad,
which requires selling a held player in week one. No-hit allows free transfers.
Hold-transfers requires zero moves and rules out a Wildcard or Free Hit rebuild
throughout the window. Save-chip rules out every chip. An automatic chip request
conflicts with hold-transfers. Subsequent real FPL transfers require a new capture.

Keep, include and avoid each accept up to fifteen unique positive persistent player
codes. A player required by keep or include cannot also be avoided. The API checks
keep against the member's captured squad and include and avoid against the capture's
roster before admitting a job. Include accepts both held and unheld roster players.
The first version deliberately refuses rival strategies and manager-news combinations.
An infeasible set of constraints is reported as no plan, never relaxed silently.
Automatic chip opportunity rebuilds obey the same human constraints as the final plan.
The existing approximate chip continuation remains experimental, not a measured MDP gain.

`preferences` is a canonical object in the advice POST and a JSON query value on GET.
It participates in the request fingerprint, job specification and cache identity.
The new `include_players` and `hold_transfers` fields are optional. Empty include and
false hold are omitted from canonical preferences, preserving legacy identities.
The worker verifies
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

Settled FPL picks can keep the original captain flag on a benched non-player after an
automatic substitution. The capture reader accepts this only with one matching
entry/week/outgoing-captain/incoming-starter substitution, preserves the original
armbands and published order, and uses the fifteen holdings for the next decision.
It neither invents a captain nor reconstructs an unknown pre-match bench order.
Such a benched-captain observation is refused as a frozen pre-match scoring decision.
FPL describes the end-of-week substitutions and vice-captain inheritance in its
[official FAQ](https://www.premierleague.com/en/news/4661030).
