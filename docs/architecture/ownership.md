# Ownership

Who may change what, which files need more than one signature, and when the live path is
frozen. The question this document exists to answer is "who approves this, and where do I put
it?" — if you cannot answer that from this page alone, the page is wrong.

Ownership means review authority, not exclusive access. Anyone may read anything and propose a
change to anything. The owner of a zone is who must approve a change to it, and who is
accountable for its contracts staying honest.

## The three roles

The review-authority names are not new. They are already used throughout the docs —
`data_contract.md:3` ("Owner: data / data mining"), `candidate_declaration_review.md:65`
("Reviewer of frozen components: the optimization/evaluation side"), and the former
architecture/CI side named in `issue43_stage_a_review.md:104`. This document collects them in
one place, and adds what each role is *for*, because a zone list says where someone may commit
without saying what they are accountable for producing.

| Role | Owns the question | Zone |
| --- | --- | --- |
| **data / data mining**<br>Data & Predictive Modeling | How do we produce the best available, leakage-safe, calibrated future information for the optimizer? | `data/`, `features/`, `prediction/` |
| **optimization / evaluation**<br>Optimization & Decision Science + Core Architecture Hardening | Given that information, what is the best decision, how do we know, and how does the core remain modular and reproducible? | `optimization/`, `evaluation/`, `uncertainty/`, `scenarios/`, `risk/`, `planning/`, `bayesopt/`, `preflight/`, `recalibration/`, `experiments/`; `live/`'s measurement and decision logic; core CI, dependency enforcement, and the current `application/` pilot |
| **platform / backend**<br>Platform, Backend & Runtime Engineering | How do accepted engine contracts become a traceable runtime, backend platform, and product without infrastructure leaking into the core? | `platform/`, `live/`'s operational surface (`ledger.py`, `tick.py`, `recommendation.py`) since the handover below, runtime registries and adapters, installed CLI, API, workers, persistence adapters, deployment, and observability |
| **shared — all three** | — | `contracts/` (when it exists), `data/schema.py`, `optimization/config.py`, `backtest/` |

The middle column is the useful half when a piece of work does not obviously belong to a
directory. "Does the residual export cross machines byte for byte?" is a data-side question
even though the writer lives in `scripts/`; "is this decision worth its risk?" is an
optimization-side question even when the code is in `live/`.

The data side's standing research programme is
[prediction research agenda](../prediction_research_agenda.md).

The platform role and its boundary with the current application pilot are fixed in
[platform and runtime boundary](platform_runtime.md). The platform consumes public application
contracts; it does not duplicate the application or engine implementation. Until the new
packages exist, the existing CODEOWNERS entries remain the mechanical review baseline. Each
implementation PR adds its own path and review authority rather than claiming an empty zone in
advance.

## Core architecture and platform are different work

Core architecture hardening stays with optimization/evaluation while that side completes the
current programme: CI gates, import enforcement, dependency reproducibility, branch/review
discipline, core logging, solver budget hooks, and the application-layer pilot. Platform work
starts above that seam: run and artifact registries, runtime orchestration, CLI/API/workers,
persistence, deployment, observability, and scaling.

This is a responsibility split, not a second implementation. When platform work needs a
missing application service, the core-architecture owner adds the smallest transport-neutral
contract in its own PR; the platform owner then consumes it. A public application contract
already consumed by the platform needs both owners to approve a breaking change.

## Shared boundaries

Four surfaces need all three owners because every layer depends on them and a casual edit
there is the most expensive kind:

- **`contracts/`** — every package will import it by construction. It is also the natural
  dumping ground for anything awkward to place, so the friction is the safeguard. See
  [dependency rules](dependency_rules.md) for what is allowed in.
- **`data/schema.py`** — the canonical column vocabulary, 17 column tuples, imported by 27
  modules in `src/`.
- **`optimization/config.py`** — where `Position` and `POSITIONS` live until `contracts`
  exists.
- **`backtest/`** — genuinely co-developed: 9 commits from the data side and 7 from the
  optimization side, and it sits directly under `experiments` in the layer order. Rather than
  award it to whoever committed most recently, it is a joint surface. This is the one entry in
  the table that is a deliberate choice rather than a description of practice.

A change to a shared boundary needs one approving review from each of the other two roles. A
change that only *reads* a shared boundary needs nothing extra.

## `live/` and the handover

`live/` began on the optimization/evaluation side — that is where all 13 of its early commits
came from, and the operational surface (`ledger.py`, `tick.py`, `recommendation.py`) was the
least safe thing in the repository to hand to a new owner mid-season.

The condition written here was that the handover happens **after** the opening gameweek is
captured, decided and settled, not before. **That condition was met on 2026-08-25**: gameweek 1
was captured (`fpl-live-20260821T143619Z-11bc603a8e1c`), decided (ledger
`data/ledger/2026-27/gw01/`, `OPTIMAL`, projected 56.08) and settled from the post-gameweek
capture `fpl-live-20260825T123200Z-120a15c72afe` (realized 26, error −30.08), with the settled
view published as `site-2026-27-gw01-settled`.

So the handover is in force. The platform/backend side owns the operational surface of `live/`
together with runtime orchestration, packaging, operational application services, and the
script/CLI shells. Core CI and dependency enforcement remain core-architecture
responsibilities; measurement logic and scientific contracts stay with the sides that own them.

What the condition was protecting, and what it is not: the risk was handing over an operational
path that had never been run end to end, so nobody could tell a defect from a misunderstanding.
It has now been run end to end once. Once is not a season — the first in-season decision (GW2,
transfers rather than an opening squad) has not happened yet, and the surface will be exercised
in ways the opening week did not exercise it. The handover transfers the ownership, not the
claim that everything about it is known.

## Live-path freeze window

No merge touching `live/`, `optimization/`, `prediction/` or `scenarios/` inside **24 hours
either side of a deadline**. The deadline is whatever the current capture publishes, not a date
written here — `run_season_tick` resolves it from the snapshot.

Inside the window the only permitted changes are a fix for a blocker found by the runbook's own
checks, recorded with the blocker report template (`../gw1_blocker_report_template.md`). Docs
and measurement PRs in other zones are unaffected.

Outside the window, any PR touching the live path carries the replay check named in
[PR discipline](pr_discipline.md).

## Open sign-offs this document clears

The former combined architecture/CI role has been referenced with pending obligations in three
places. These remain cross-system runtime/reproducibility reviews and therefore stay with the
platform/backend role unless the acceptance record explicitly reassigns them:

| Where | Item |
| --- | --- |
| `../issue43_stage_a_review.md:109` | "Reviewed by the architecture/CI side: **pending**" |
| `../issue43_candidate_declaration.md:59` | "Reviewed by the architecture/CI side: pending" |
| `../issue43_handoff_acceptance.md:45` | Item 17: freezing requires all three owners; the architecture/CI side's review is pending |

These stay open. This document does not grant the sign-off — it says who owes it.

## The calibration seam

Calibrating prediction residuals into intervals or quantiles is the data side's **research**
responsibility — it is the tail end of "produce the best available future information", and the
open work on it (#38's calendar-aware recalibration) starts from prediction residuals.

The `uncertainty/` **package** stays with optimization/evaluation, where all of it was written.
Reassigning a package nobody is currently changing, on the strength of a research plan, would
be churn for a hypothetical.

The trigger for revisiting is specific rather than "later": **when the prediction side starts
producing a distribution rather than a point estimate.** That is not a preference, it is a
contract change. `prediction/integration.py:94` projects the hand-off table down to the six
required columns, so `PredictionSnapshot` drops `expected_points_stddev`,
`prediction_interval_lower`, quantiles — and even `fixture_count` — on the way through. Today's
distributional objects (`CalibratedProjectionResult`, `ScenarioSet`) sit *beside* the snapshot
rather than inside it, and `ScenarioSet` contains one as its point-estimate anchor.

So the day a probabilistic hand-off is proposed, it touches `REQUIRED_COLUMNS`
(`optimization/validation.py:15`), which is a shared boundary and needs all three owners
anyway. That conversation is the right moment to decide where `uncertainty/` belongs, because
by then it will be a decision about live code rather than about a roadmap.

## Unresolved

- **`data/identity.py`** sits in the data zone but has no importers inside `src/squadopt` —
  only `scripts/` and `tests/`. Whether it is a public utility, a contract, or dead is the data
  side's call to make and record.
- **`recalibration/` and `preflight/`** are assigned to the optimization/evaluation side on the
  strength of who wrote them (2 commits each). If the data side ends up doing the recalibration
  work in practice, move it here rather than working around the table.

## Verification

Ownership claims about who wrote what are checkable:

```bash
git log origin/develop --format='%an' -- src/squadopt/backtest | sort | uniq -c | sort -rn
```

Run it for any zone. If the table and the history disagree for a whole package, the table needs
a deliberate decision rather than a quiet edit.

Last reviewed against `b031ef1` (PR #110).
