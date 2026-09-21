# Prediction review: scope and acceptance

This is the scope of [#749](https://github.com/MyManDev/football-squad-optimizer/issues/749),
started by the owner on 20 September 2026. The initial read-only audit is pinned to
`054baa56cff8a6390bb5738bca2e36a2141cd140` on `develop`. An open PR is not part of that
snapshot: [#748](https://github.com/MyManDev/football-squad-optimizer/pull/748), head
`a3da26863e138155688a16176a4a09b0b82c386e`, is the data owner's pending appearance handoff work.
These documents describe source and existing records, not a fresh production inspection.

## Write territory

| Directory | Work in this programme |
| --- | --- |
| `src/squadopt/evaluation/` | Pure gate and post-projection candidate arithmetic. |
| `scripts/` | Thin declared measurement runners and, conditionally, the readout instrument. |
| `docs/` | Scope, audit, decision map, preregistration, measurement record and index. |
| `tests/` | Synthetic verification of the new arithmetic, refusal paths and runners. |

Every candidate is a **post-projection transformation of the frozen
`phase_c_component_oof_v1` handoff**. Reading source outside these directories is necessary
to trace the decision. Writing it is not part of this assignment. M2 changes no executable
line; correcting the discrepancy while recording it would erase the audit baseline.

## Boundaries and their reasons

| No change to | Reason and route for follow-up |
| --- | --- |
| `src/squadopt/prediction/`, `src/squadopt/features/`, `src/squadopt/data/` | The data owner is working there. Producer fixes belong in a separately assigned issue, not a competing PR. The confirmed owner is `@SpeedyV5`. |
| `projection_handoff_v1`, including `live/recommendation.py::InSeasonProjection` | This is a persisted producer/consumer agreement. #748 already owns widening it; a second implementation would fork identity and replay semantics. |
| The nine-column allowlist named in #749, including adding `position` | No handoff/schema widening is authorized. Column counts belong to their specific boundary: the component input tuple currently has eight names (`prediction/components.py:21–30`), whereas the generic optimizer contract has six required columns plus an optional tier. None may be silently reinterpreted or widened to satisfy an audit finding; shared boundaries require all owners. |
| `FEATURE_GENERATION_CONTRACT_VERSION` | Existing measurements name that contract in their provenance. Changing it changes what their evidence refers to. |
| `optimization/`, `planning/`, `live/`, `scenarios/`, application and web implementations | The experiment measures frozen outputs; it does not change member decisions or their publication. Findings here are referrals. |
| Runtime state and `data/` writes | No live queue/cache/job/run state inspection, manual data writes, capture generation or operational replay is needed for the audit. Source and committed records are sufficient. |
| 2025–26 holdout inputs | M5/M6 declare the existing 147 development folds only. No loader, discovery, listing or hashing of the locked season is part of this candidate. |
| DEFCON modelling | The canonical labels are absent and the only raw season identified in #749 is the locked holdout. A new source/schema/model programme cannot be smuggled into calibration. |
| Deployment, promotion, version pinning, merge, tags, weekly execution or backend restart | A research verdict is not operational authority. No member-facing number is published by this programme. |

The 9 October 10:00Z–11 October 10:00Z live-path freeze remains in force. Timing copy,
proved-window fixtures, #648 remeasurement, Oracle B7 account choices and #742 real dispatch
retain their separate authorization requirements.

## Deliveries, in dependency order

1. **M1–M3, audit only:** this scope, the [inconsistency ledger](prediction_inconsistency_ledger.md)
   with two source anchors per finding, and the [decision map](prediction_decision_path.md).
   Distinguish stale prose from an actual defect and from a recorded deferral; count which
   closures need no measurement. Do not convert a proposal's seed into a finding without checking it.
2. **M4, gate:** within-position ranking first, a numerical error guardrail, and paired
   realized squad points. Apply the template to three historical records without rerunning
   them. Missing evidence means an unestablished clause, never an invented passing value.
3. **M5, preregistration:** commit the exact monotone appearance transformation, prior-only
   fitting population, numerical M4 thresholds, fingerprint and refusal rules before reading
   any candidate fold. Existing aggregate records may motivate the declaration.
4. **M6, one measurement:** report OOS Brier/reliability, forecast mass on nonplayers,
   within-position ranking and paired squad difference with interval. Record and index the
   verdict, including failure. A second variant is a new candidate and is not authorized.
5. **M7, applicability:** make the historical/non-DEFCON versus live/DEFCON scoring break
   prominent in the agenda and index. A historical verdict does not establish live benefit.
6. **M8, conditional on M4/M6 finishing early:** build `measure_top100_effect.py` using
   existing readers and synthetic tests. Refuse before settled GW12, do not solve and do
   not take a real readout. The preregistered GW12/GW20 dates remain binding.

Each topic gets its own `codex/` branch, isolated worktree and PR to `develop`; existing
matching work is reused. New PRs receive the full local gates and full CI. Heavy test runs
are serialized, browser tests use at most two workers, and a tested tree is not edited
while its run is active. Previous task-specific test exceptions do not carry forward.

Completion means delivered, reviewed work and an explicit account of verified and
unverified claims. It does not mean a positive candidate verdict or measured top-100 ability.
