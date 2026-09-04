# Candidate Declaration Review Checklist

## Purpose

The formal #43 development gate runs **exactly once** per frozen declaration. This
checklist turns that rule into an ordered procedure with explicit stop points, so the
gate cannot be re-run quietly, tuned against, or executed before its inputs are frozen.

Companion documents: [candidate gate](candidate_gate_spec.md),
[production prediction spec](production_prediction_spec.md),
[handoff acceptance checklist](handoff_acceptance_checklist.md).

## Ordered procedure

### Stage A — before any formal execution

1. **Candidate complete.** Implementation merged; synthetic/smoke tests pass; the four
   quality gates pass on the merged tree.
2. **Handoff accepted.** Every applicable item of the
   [handoff acceptance checklist](handoff_acceptance_checklist.md) passed.
3. **Declaration drafted.** A typed `CandidateDeclaration` exists with: candidate ID,
   model name/version, feature contract version, changed component
   (`expected_points_rate` for #43), change summary, frozen components (at minimum:
   expected-minutes stage, cold-start ladder, availability rule, optimization
   contract, promotion gates), evaluation objective
   (`single_gameweek_realized_squad_points_v1`), and source reference.
4. **Declaration reviewed.** All three owners have read the declaration. The review
   confirms the changed component is singular and every frozen component is actually
   unchanged in the code.
5. **Fingerprints frozen.** `declaration_fingerprint` and the benchmark
   `configuration_fingerprint` are computed and recorded (issue comment or committed
   doc) **before** execution. From this point the declaration and the benchmark
   configuration are immutable.

**Stop point:** if anything in stages 1–5 changes after step 5, the freeze is void.
Return to step 3 with a new candidate/declaration version. There is no "small fix"
exception — a changed candidate is a new candidate.

### Stage B — the formal run

6. **One execution.** The declared-candidate development benchmark runs once, from a
   clean tree at a recorded commit, against the frozen fingerprints. The command,
   environment, and outputs are archived together.
7. **Fingerprint match verified.** The report's recorded declaration/config
   fingerprints equal the frozen values from step 5. A mismatch invalidates the run —
   it is not the formal run.

### Stage C — after the run

8. **Verdict recorded as produced.** Both possible verdicts
   (`eligible_for_holdout_evaluation` / `no_promotion_control_retained`) are final for
   this declaration. The verdict, all gate margins, and every failed gate are recorded
   even when — especially when — the candidate fails.
9. **No post-hoc tuning.** Adjusting the candidate after seeing the gate result and
   re-running requires a **new** declaration with a new fingerprint, and the report
   must reference the failed predecessor. Iterating silently against the gate is the
   exact failure mode this procedure exists to prevent.
10. **Holdout stays separate.** A passing development verdict does not open the 2025-26
    locked holdout. The holdout evaluation is a separately controlled step with its own
    single-execution discipline, and BO/DoE search never touches it.

## Roles

- **Declaration author:** the prediction side (candidate identity, contracts).
- **Reviewer of frozen components:** the optimization/evaluation side.
- **Executor of the formal run:** anyone, but the executor may not amend the
  declaration; steps 6–7 only.

## Record-keeping

Each formal run leaves, in one place: the declaration JSON (or its committed source),
both fingerprints, the benchmark JSON/Markdown reports, the repository commit, the
dataset snapshot identity, environment versions, and the verdict. A run missing any of
these cannot support a promotion claim.
