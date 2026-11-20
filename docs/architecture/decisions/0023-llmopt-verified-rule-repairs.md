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

When the page finds a three-week conflict before the first solve, the first
request is already an edited candidate. The browser includes the original
hard rules as bounded, independently validated preference fragments and
forced Wildcard weeks in `run.repair_origin` on each candidate and replay.
This can represent contradictory original rules, such as two exact counts
for one club. The server binds their canonical content to the run's existing
capture and member binding. This adds no field to the durable run record and
does not change the ordinary advice address. For a new candidate the server
requires one permitted rule relaxation from that same origin, even if the
first candidate failed. Both candidates count toward the limit of two.
Selection still requires the exact frozen replay of a completed witness.

For a one-week repair with a total allowance, compute the main plan under
the edited hard rules and use its decisions and proof status for the priority
calculation in the same worker. The candidate's private answer retains both
this main and the preference-selected plan. On selection, reconstruct J from
the saved main on the same inputs and rerun the priorities in a fresh worker.
The candidate and its selection each share one 120-second ceiling across all
their solves and each consume one four-unit worker reservation.
The initial device receipt reserves storage for both candidate digests and
the selected replay so later reservations fit if the tab reaches its quota.

Selecting a proposal recalculates the selected concrete plan and checks its
decision content and net points against the witness on the same data. On the
device rerun the edited request. On the server the existing frozen-week
contract can replay the chosen decisions under the edited rules. A replay
pin is internal to verification and is never added to the member's draft.
Publish the selected result only after agreement. A stale input, unfinished
replay or mismatching witness cannot stand in for the selected plan.
Repeated reads of a completed selection reuse its checked result. A tab joins
an active worker for the same run, edit and stage. If navigation interrupts
that worker, or a reload finds its reservation without an answer or terminal
failure, the same edit may recover under the original confirmation and input
fingerprint. Each new worker requires current release permission and another
four units. The interrupted attempt stays charged. Recovery retains the two
distinct candidate slots, the single selected edit and the selection allowance.
Stored solver failures remain terminal, including failures in older receipts
whose cause cannot be distinguished. These records stay private to the tab.

When an ordinary 122-unit three-week job admitted before rollback finishes with the release
switch closed, its existing run receipt may store the SHA-256 of the exact
answer bytes. A repair can use that digest only with the same run's completed
job, immutable request specification and current capture. Earlier receipts
remain readable. A cache hit alone supplies no such proof. This private
completion record grants no catalogue identity. Only provenance written
while the release switch was open can identify a plan for conversation.
A 366-unit preference bundle retains its solver journal and cannot supply
the private completion proof for an ordinary repair.

Run stages describe admission and do not enter ordinary advice-cache identity.
Repairs use the squad optimizer with the original projection model and data.
They require no changes to either model
endpoint and never contain credentials. A saved repair search retains its
diagnosis for the same squad and deadline. After rollback and reload, show
that conflict as read-only text in the selected language. Restoring the
explanation neither resumes the run nor submits an edit. A changed squad
retains only the member's rules under the existing session policy.
Release controls and activation are addressed separately.

## Validation

Exercise club, bank, hit, frozen-week and chip conflicts in Turkish and English
on a phone viewport, including selection and recomputation. Check the actual
device and server budget paths, failed and unavailable candidates, stale data,
equal plan content and the distinct conflict, missing and exhausted outcomes.
