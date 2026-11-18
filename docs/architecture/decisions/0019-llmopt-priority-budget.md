# ADR 0019: Priority layers within one preference job

- Status: proposed
- Date: 2026-11-19
- Decider: project owner
- Related: ADR 0018; PR #1466

## Decision

The required-rule plan is one job. Preference calculation is one further job, containing
at most three successive priority layers, followed by a points tie break. Layers are not
jobs. Both one-week and three-week calculations remain on the server in this phase.
All solver calls consume the admitted run's existing 84/488-unit capacity; four remains
the absolute job ceiling. No additional capacity is created for a preference layer.

Priority is an integer from 1 through 3; 1 is strongest. Unspecified priority is 2.
Within each layer maximize the number of satisfied rules. Freeze that number before
solving a weaker layer, rather than freezing an arbitrary subset of equally ranked rules.
Sort canonical rule identities before constructing variables. Finally maximize the same
integer-scaled net-points objective as the required-rule plan. This avoids writing-order
weights and floating-point boundary comparisons.

`max_total_cost_tenths` is an optional nonnegative integer in draft preferences. When
present, the required-rule plan's computed objective J supplies a lower bound of J minus
that many tenths. J is the returned feasible value even if its optimality is unproved;
that fact stays in internal metadata. Neither the page nor a client-supplied numeric
claim establishes J. Individual ceilings do not start price jobs in this mode and do not
constrain the result separately. Total cost is the difference between the two computed
plans, never a sum of individual prices. A better preference plan has zero concession.

With no total limit, existing individually bounded preference behavior is retained.
Its individual prices and combined decision must be calculated sequentially inside the
single preference job before that execution path can replace the existing page path.
An incomplete bundle implementation must not silently change legacy acceptance rules.

Only completed layers may be published as the preference outcome. If remaining work
cannot start another solve, retain the last completed layer, or the required-rule plan
if none completed. A layer is complete when its count is proved optimal (including a
feasible witness satisfying every rule in that layer). The last points tie break can
retain its feasible incumbent. No incomplete search is described as an optimum.

Hard rules are applied outside reification. Soft rules get separate satisfaction literals;
conflicting soft rules may remain unsatisfied without making the hard model infeasible.
No key handling changes. New interpretation fields travel only through prompt/check;
solver preferences and results travel through the existing advice boundary. Every field
in a provider-facing schema has an explicit type.

## Contracts and rollout

Preference, result and job changes require checked-in schemas in the same PR. Old absent
fields preserve old identities and remain readable. A transport switch must be integrated
through API admission, immutable job specs, worker computation and result validation before
the page sends it. Until those boundaries are complete, publish the missing work explicitly
and retain the existing working path. Browser migration belongs to the next phase.

## Verification

Compare tiny football models against independent enumeration of all transfer packages,
including jointly expensive rules, contradictions, exact concession boundaries, an
unproved reference and equal-priority permutations. Count actual admitted jobs on the
unchanged Phase 1 identities, separately from internal solver calls. Exercise the editor
and a conversation requesting a priority and a total 1.5-point concession in both languages.
