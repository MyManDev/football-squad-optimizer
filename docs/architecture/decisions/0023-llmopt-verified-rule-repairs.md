# ADR 0023: Offer a rule edit only after computing a feasible plan

- Status: proposed
- Date: 2026-11-20
- Decider: project owner
- Related: ADR 0018, ADR 0020, ADR 0021 and ADR 0022

## Decision

Distinguish a known rule conflict, missing inputs and exhausted computation. A
contradiction in the supplied rules, an explicit unavailable chip right or a
solver's proved infeasibility can establish a conflict. Unknown chip history,
an absent reference week and missing projections are missing inputs. A stopped
search without a feasible witness cannot establish infeasibility. Each outcome
has one plain localized sentence. Use neutral rule names for conflict groups.

Consider at most two edits, in deterministic order, to the specified club
count, bank floor, hit rule, frozen week or requested chip. Preserve all other
hard rules, dates, player restrictions and preferences. Name the exact rule
and the proposed change on each action. An edit suggested by a static check
or an older infeasibility record is only a candidate until the normal planner
returns a valid plan for the edited request on the same data.

One confirmation owns the failed plan, candidate computations and selection.
Retain its capture and run identity. Use the device for one-week repairs with
verified local inputs. Three-week candidates use normal durable advice
admission. A repair stage may continue a proved infeasible base, while an
ordinary follow-up still requires a successful base. A pre-submission conflict
may start a confirmed run with the first well-formed edited request. Leave
capacity for selection, use at most two candidates and stop when capacity
is insufficient. Across all stages, the four-job and 84/488-unit ceilings
remain binding. Missing data and exhausted capacity produce no new proposal.

Selecting a proposal recalculates the selected concrete plan and checks its
decision content and net points against the witness on the same data. On the
device rerun the edited request. On the server the existing frozen-week
contract can replay the chosen decisions under the edited rules. A replay
pin is internal to verification and is never added to the member's draft.
Publish the selected result only after agreement. A stale input, unfinished
replay or mismatching witness cannot stand in for the selected plan.
Repeating or restoring a selection must not allocate additional attempts.

Run stages describe admission and do not enter ordinary advice-cache identity.
Repairs use the football planner. They require no changes to either model
endpoint and never contain credentials. Preserve readable older diagnoses
and saved sessions. Release controls and activation are addressed separately.

## Validation

Exercise club, bank, hit, frozen-week and chip conflicts in Turkish and English
on a phone viewport, including selection and recomputation. Check the actual
device and server budget paths, failed and unavailable candidates, stale data,
equal plan content and the distinct conflict, missing and exhausted outcomes.
