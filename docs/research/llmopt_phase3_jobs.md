# One preference job on the frozen twenty member-weeks

The [record](llmopt_phase3_jobs.json) was produced by
`89e380b9d30e481324dce90a51a168038593b3e5` with
`python -m docs.research.llmopt_phase3.measure`.

All twenty unchanged Phase 1 member-weeks were replayed at both windows and in
both preference modes: eighty run records. The local public API, durable run
admission, immutable requests, real worker and solvers performed the calculation.
Frozen point tables were consumed directly; forecasting and scoring were guarded
against invocation. Scenario chip rights and timestamps are replay controls, not
claims about live entitlements or deadlines. No tests or owned CI ran alongside
the measurement, and no live football or advice service was contacted.

| Weeks | Preference mode | Runs | Main cache hits | Expected infeasibilities | Maximum server jobs per run | Maximum charged units in one job | Largest job allocation |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | legacy_prices | 20 | 0 | 4 | 2 | 2.816995632 | 63 |
| 1 | priority_total | 20 | 16 | 4 | 1 | 1.736026260 | 63 |
| 3 | legacy_prices | 20 | 0 | 4 | 2 | 335.901700784 | 366 |
| 3 | priority_total | 20 | 16 | 4 | 1 | 61.197159227 | 366 |

All runs stayed within two server jobs and every actual job receipt stayed within
its allocation. The four contradictory hard-rule cases per group remain expected
infeasibilities rather than invented numeric plans. 192 repeated requests
after service reconstruction opened zero extra jobs.

Legacy mode is cold and includes the main job, two individually priced components
and the selected combined component. The three components execute sequentially
inside one follow-up job. Total mode explicitly reuses the completed main answer
when feasible; its measured one-job count is a warm-main count, not a cold latency
claim. Actual API/worker tests independently exercise a cold main plus one total
preference job at both windows. Layers never create queue jobs.

The main reserves 21/122 units and the preference bundle 63/366, within the
unchanged 84/488-unit run capacity. These are ceilings rather than work that must
be consumed. As declared in ADR 0019, the priority count kernel retains its inner
20/60-unit search ceiling; an exhausted kernel returns its last completed layer,
even when the enclosing bundle reservation has spare capacity. Actual work and
exhaustion remain recorded without clamping or larger tolerances. Completed
priority layers observed in the total-mode outcomes were:

- 1 week(s), completed layers 1,2,3: 16.
- 3 week(s), completed layers none: 1.
- 3 week(s), completed layers 1: 5.
- 3 week(s), completed layers 1,2: 1.
- 3 week(s), completed layers 1,2,3: 9.

The main objective J comes from certified cached decisions, with its original
global proof flag preserved. A fixed-path certificate does not upgrade an unproved
main plan. Computed costs are signed; no provider response supplies plan numbers.
This admission/work replay makes no realized-score or global-quality claim.

`tests/unit/test_priority_preferences.py` separately compares tiny models with
independent enumeration of all sixteen transfer packages and legal lineups, all
six equal-priority writing orders, exact and joint concession boundaries, unproved
J and interrupted layers. `tests/unit/test_llmopt_preference_bundle.py` checks the
actual API and worker. Eight `web/e2e/llmopt-priorities.spec.ts` flows exercise both
languages, both windows, both modes, pending/completed reload and phone overflow.

The producing commit includes the Phase 2 named-chip capacity fix only after all
five Phase 2 CI jobs passed. Earlier failed diagnostic checkpoints are not reused
or relabelled as acceptance. Source hashes normalize line endings; frozen inputs
and Phase 1 artifacts remain unchanged. Their manifest SHA-256 is
`fdbd303a04679d1b866f366c56b72cf0fe056b6e9f52c2ed752f0ae88d0032fc`.
