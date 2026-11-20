# ADR 0019: Priority layers within one preference job

- Status: accepted
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

Only a proved count completes a layer. A feasible witness meeting every rule also proves
the count by attaining its upper bound. Freeze completed counts and stop counting at
the first incomplete layer. Maximize net points with the counts proved so far, even
if a weaker layer stopped early. If no count was proved, return the certified main plan.
Keep the higher-scoring witness when two plans attain the same proved counts.
In the result, only completed layers contribute to `satisfied` and `left_out`.
`unsearched` contains all rules from the other layers, including any the returned
plan happens to satisfy. Each rule appears exactly once.

Hard rules are applied outside reification. Soft rules get separate satisfaction literals;
conflicting soft rules may remain unsatisfied without making the hard model infeasible.
No key handling changes. New interpretation fields travel only through prompt/check;
solver preferences and results travel through the existing advice boundary. With the
release setting off, the schema sent to the provider preserves the exact bytes of the
develop schema at `177000ec2cfcd0eb525f9253cd46afd75b7ac733`. The new nullable fields
use `anyOf` with an explicitly typed branch for each alternative. Object branches declare
their properties, required fields and `additionalProperties: false`.

## Contracts and rollout

Preference, result and job changes require checked-in schemas in the same PR. Old absent
fields preserve old identities and remain readable. A transport switch must be integrated
through API admission, immutable job specs, worker computation and result validation before
the page sends it. Until those boundaries are complete, publish the missing work explicitly
and retain the existing working path. Browser migration belongs to the next phase.

### Public execution boundary

The following public execution boundary connects admission, immutable requests,
worker computation and the page. The internal kernel alone does not establish
the two-job acceptance condition.

Use a closed `llmopt_preference_bundle_v1` contract on the existing advice boundary.
The full backend advertises the capability only when durable run admission, immutable
specs, the cache and the bundle worker are wired together. Old readers and confirmed
sessions retain their original transport; new confirmations pin the chosen mode.

One preference job reserves three former job allocations: **63 units at one week**
or **366 at three weeks**. Together with the main job this is exactly the existing
84/488-unit run capacity. The client cannot choose an allocation. A child calculation
cannot reset the parent meter. In total-allowance mode, certification, count searches
and the points pass share the bundle's full remaining allocation. After certification,
hold a quarter of the remaining work and wall time for the points pass. All count
layers share the other three quarters. The points pass may also use everything the
counts did not spend. The proportion leaves a final search available after an
interrupted count without giving each count a fresh allocation. Certificates are
charged work in the same job. If the durable admission limit shortens a large final
points call and that call reaches its granted limit, one further points call can
use the unspent balance. It retains all completed counts and the highest score
already attained under those counts.

Each ordinary price or combination may start with the positive balance actually
available, up to 21 or 122 units. A total-priority calculation shares all of
the bundle's remaining 63 or 366 units. Charge actual solver stop granularity.
Neither rounding nor a tolerance can create another unit.
A component solved with less than its ordinary allocation belongs to the bundle
result. It cannot populate the shared full-allocation answer at that address.

Persist a bundle's solver grants before work starts. Settle each returned call
with its measured work and keep the original job identity across queue lease
recovery. A newer queue attempt fences the old worker and charges any unreturned
grant before requesting more work. A terminal failure releases unused capacity
for other eligible requests in that run. The existing job count and work
ceilings continue to apply across processes and retries. Ordinary jobs and old
receipts retain their original one-attempt accounting.

A single grant may exceed a former job allowance. If such a grant would consume
the final balance, retain one quarter of a former allowance for same-job recovery
(5.25 units at one week or 30.5 at three). A grant of up to 21 or 122 units
may use the final balance. Thus a lost larger call leaves retry capacity, and
a lost smaller call costs at most one former job. A later call can spend a held
tail. Queue retries retain their existing finite attempt limit and never reset
the ledger.

The server derives the reference cache key from the main request and verifies it against
the durable run's base. No client objective or reference payload is accepted. Cached
transfer, chip and lineup decisions are certified against the current net-points model;
the resulting J is recomputed from its integer coefficients. This model already uses
the game's transfer limits. Unproved main results retain their unproved reference flag.
In the preference model, Triple Captain contributes the captain's extra score exactly
when played. Bench Boost contributes each benched squad member's score exactly when
played. These identities hold during certification and count search as well as during
points maximization.

Without a total limit, package the existing two single-price requests and the existing
combined request into one execution. The page's existing compiler produces reachable
accepted-price combinations, preserving legacy order, conflicts and individual ceilings.
Two distinct price slots normally need four combinations. Rules sharing a slot can have
different ceilings, so enumerate their reachable threshold intervals rather than treating
a slot as one acceptance bit. Sixteen rules admit at most 289 combinations. Repeated
choices share their canonical identity. This preserves legacy semantics without duplicating
its rule compiler on the server. Encode child preference differences relative to the main request so frozen
weeks are not duplicated. Keep the existing request size limits and refuse an oversized
bundle before admission. A completed component that received its ordinary allocation
enters the ordinary answer cache even if the initiating run closes, as in ADR 0018.
The bundle query on a result read accepts up to 4,096 decoded characters. A compact
JSON bundle that fits the 4,096-byte submission body always fits this read limit.
The existing standalone preferences query keeps its separate limit.
Closing prevents new admission rather than discarding completed computation.
The parent response retains the main answer and a checked catalogue of computed
components and the selected outcome; it does not relabel a component as the main
request. Run identifiers never enter an answer address.

An incomplete points tie break stopped by the wall clock cannot replace the last completed
layer witness. Its actual completion status is separate from the public FEASIBLE plan
status, which never claims that the resulting net score is globally best.

### Confirmed product decisions

Readers of earlier saved results use the original program and `completed_priorities`
to distinguish a pending search from an excluded rule.

Explicit new priorities require an explicit total allowance. Ask for that allowance rather
than inventing one or silently ignoring a priority. An old request without either field
keeps its existing individual-price behavior. This resolves the conflict between new
lexicographic semantics and the required legacy behavior without granting an unstated loss.

A soft Wildcard combined with a total allowance remains unsupported until its chip domain
can be shared correctly with J. Refuse it before starting a job. Keep ordinary legacy
Wildcard pricing intact; do not silently weaken an explicit chip-saving requirement.

Unknown provider fields whose value is null retain the legacy ignored-field behavior.
Non-null unknown fields and malformed page requests remain contract errors.

## Verification

Compare tiny football models against independent enumeration of all transfer packages,
including jointly expensive rules, contradictions, exact concession boundaries, an
unproved reference and equal-priority permutations. Count actual admitted jobs on the
unchanged Phase 1 identities, separately from internal solver calls. Exercise the editor
and a conversation requesting a priority and a total 1.5-point concession in both languages.
