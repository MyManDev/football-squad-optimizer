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
plans, never a sum of individual prices. The difference is signed: a better preference
plan has a negative cost. Legacy individual price ceilings retain their zero-floor rule.

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

### Public execution boundary

Use a closed `llmopt_preference_bundle_v1` contract on the existing advice boundary.
The full backend advertises the capability only when durable run admission, immutable
specs, the cache and the bundle worker are wired together. Old readers and confirmed
sessions retain their original transport; new confirmations pin the chosen mode.

One preference job reserves three former job allocations: **63 units at one week**
or **366 at three weeks**. Together with the main job this is exactly the existing
84/488-unit run capacity. The client cannot choose an allocation. A child calculation
cannot reset the parent meter. Count layers share their existing 20/60-unit allowance.
Certificates are charged work, not additional jobs.

The server derives the reference cache key from the main request and verifies it against
the durable run's base. No client objective or reference payload is accepted. Cached
transfer, chip and lineup decisions are certified against the current net-points model;
the resulting J is recomputed from its integer coefficients. This model already uses
the game's transfer limits. Unproved main results retain their unproved reference flag.

Without a total limit, package the existing two single-price requests and the existing
combined request into one execution. The page's existing compiler produces the at most
four accepted-price combinations, preserving legacy order, conflicts and individual
ceilings. Encode child preference differences relative to the main request so frozen
weeks are not duplicated. Keep the existing request size limits and refuse an oversized
bundle before admission. Completed component answers may be cached only inside the
existing successful-completion and cancellation boundary, so later edits reuse them.

An incomplete points tie break stopped by the wall clock cannot replace the last completed
layer witness. Its actual completion status is separate from the public FEASIBLE plan
status, which never claims that the resulting net score is globally best.

### Conservative morning decisions

Explicit new priorities require an explicit total allowance. Ask for that allowance rather
than inventing one or silently ignoring a priority. An old request without either field
keeps its existing individual-price behavior. This resolves the conflict between new
lexicographic semantics and the required legacy behavior without granting an unstated loss.

A soft Wildcard combined with a total allowance remains unsupported until its chip domain
can be shared correctly with J. Refuse it before starting a job. Keep ordinary legacy
Wildcard pricing intact; do not silently weaken an explicit chip-saving requirement.

## Verification

Compare tiny football models against independent enumeration of all transfer packages,
including jointly expensive rules, contradictions, exact concession boundaries, an
unproved reference and equal-priority permutations. Count actual admitted jobs on the
unchanged Phase 1 identities, separately from internal solver calls. Exercise the editor
and a conversation requesting a priority and a total 1.5-point concession in both languages.
