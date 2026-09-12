# ADR 0007 — Move the operational scripts into the installed package, in one change

- **Status:** accepted (merged 2026-09-10 as `e95d2cd3`, [PR #456](https://github.com/MyManDev/football-squad-optimizer/pull/456))
- **Date:** 2026-09-10; recorded as an ADR on 2026-09-12
- **Decider:** repository owner, on the 2026-09-09 review's recommendations
- **Supersedes:** the branch records `enterprise_transition.md` and `enterprise_acceptance.md`,
  deleted with this ADR; their text is readable at
  `git show e95d2cd3:docs/architecture/enterprise_transition.md` and
  `git show e95d2cd3:docs/architecture/enterprise_acceptance.md`. The
  [developer handoff](../enterprise_developer_handoff.md) stays as a dated 2026-09-10 record.
- **Related:** [ADR 0001](0001-modular-monolith.md), [ADR 0005](0005-persistence-boundaries.md),
  [ADR 0006](0006-backend-hosting.md), [dependency rules](../dependency_rules.md),
  [operations inventory](../operations_inventory.md), [advice capacity](../advice_capacity.md)

## Context

The 2026-09-09 repository review was run against develop `a85c7bdd`. Before anything from it
was implemented, `#454` (`0d9bd462`, 2026-09-09) realigned develop to the published `main`
tree; the earlier development history went to `archive/pre-main-alignment-20260909`, and
`#440`/`#442` were closed during that owner-authorized consolidation with every tip archived.
`0d9bd462` is therefore the baseline of the transition: published-main runtime plus
documentation, with the review as input rather than as a record of anything done.

The review's constraints were kept as given: retain the modular monolith of ADR 0001,
deterministic domain calculations, versioned public contracts, independent API and worker
processes (ADR 0006) and immutable scientific evidence. Fifteen work items R01–R15 were
implemented as topical commits on one branch, `codex/enterprise-software-transition`, whose
last code commit was `0eaed701`. Throughout, three states were kept apart: code implemented,
a test passed in a named environment, and the live system accepted.

## Decision

**Merge the branch as one change** (`e95d2cd3`, the owner's decision), reviewed against
develop and the real gameweek 4 publish, with every published number byte-identical across
both trees; re-land the defects the review confirmed, and the fixes `#454` had dropped, as
separate pull requests. What the change did:

- **Layer split.** The shared player vocabulary moved to `contracts.players`, promotion
  policy and bootstrap statistics from `experiments` to `evaluation`, and the repeated solver
  decision support to `optimization.decisions` (R11, R12). The five `import-linter` exemptions
  were removed rather than relocated; `lint-imports` runs with zero exceptions plus a separate
  prohibition on direct API-to-engine imports.
- **`platform/` runtime.** Weekly scripts, publication producers, capture collectors and the
  queue moved into the installed package behind typed `application` (workflows, advice
  capabilities, evidence and publication builders) and `platform` (filesystem, network capture,
  queue, process pool, metrics, backup, CLI/Git adapters) boundaries. The queue's one module
  became `queue_contracts`, `file_advice_queue` and `advice_queue`; the weekly runner became
  `weekly_operations`, `weekly_journal` and `weekly_publish` (R02–R05, handoff owner map).
- **Private run directories.** A weekly run journals its request, code identity, stage
  attempts and input/output hashes in `data/runtime/weekly/<run-id>/run.json`, and its default
  preview is `data/runtime/weekly/<run-id>/preview`, so a run no longer writes into the tracked
  `web/public` tree. Projection handoffs are retained at
  `handoffs/by-capture/<capture>/<content-sha>.json` before the `<season>-gwNN.json` alias
  changes (R04, R05).
- **Compatibility shells for one release.** Old import locations and `scripts/` entry points
  re-export the moved objects and keep their CLI flags, under ADR 0001's re-export rule; some
  are imported by real research callers (`scripts/_phase_e_live.py`), so they are not
  test-only conveniences.
- **Publication commits `web/public/data`.** `--publish` succeeds as a receipt of an open
  PR/commit or of no change, not of the live site; merge, `main` CI, tag and deploy remain
  separate. This keeps ADR 0005's rule that published data is a reproducible release projection.

## Status of R01–R15 at the merge

| Accepted at `e95d2cd3` | Evidence recorded in the branch records |
| --- | --- |
| R01 archive reconciliation | 71 Python and 19 strategy-control tests |
| R02 queue recovery, R03 API/web validation and cancellation | 66 and 59+143 focused tests; browser/API/worker/cache acceptance |
| R04 retention, backup and restore tooling | 59 tests including a synthetic domain restore |
| R05 journaled weekly runner and resume | 239 tests; isolated wheel run/resume/status |
| R08 artifact-specific evidence declarations | 54 tests; historical evidence unchanged |
| R11, R12 shared vocabulary, solver support, member page, publication | 163, 209, 392 and 48 tests; fingerprints and model/results unchanged |
| R13 CI and browser coverage, R15 document organisation | first `#456` CI run: Python 3.11 and 3.13 each 4,778 passed, 14 skipped; 70 Playwright and 491 web unit tests |
| R14 capacity measurement | 18 scenarios in 6 configurations, indexed by `#457` |

**Still open**, exactly as the records left them:

- R06: no live backend host, shared mount, independent external backup destination or running
  weekly scheduler was verified; local drills and Compose do not establish those (ADR 0006's
  probe is unmet). The realized replica count for R14 remains host-specific.
- R07: İbrahim's club-evidence delivery. The capture/replay/provenance chain landed after the
  merge (`#459`, `#461`, `#463`, `#467`, gathered by `#470`); network/model activation and its
  cost remain a separate explicit decision.
- R09 needs future pre-deadline decision captures and settled outcomes; R10's Phase D/E
  admission gates stay in force and are not passed by any code change.
- Three Windows directory-rename permission failures were recorded and not retried; long
  Windows paths are not supported by this acceptance.

## Consequences

- **The realignment dropped work, and it came back one PR at a time** (`#457`–`#469`):
  `#458` re-lands the canonical member address and CORS (`d753a51c`), `#464` the three live
  replay guards and the ledger rename retry (`#443`), `#468` the pruning of member documents a
  publish did not produce, `#459` the frozen coding prompt with its locator's overlap bug fixed
  (`#445`); `#460` made the weekly run replay across commits and refuse in preflight, `#466`
  handled handoff and backup paths past Windows' `MAX_PATH`, `#465` and `#469` corrected the
  published-name guard, `#457` gave the capacity record its index row.
- **The layer order alone could not keep the laboratory out of the product**: the advice worker
  was loading 43 laboratory modules. `#471` added the forbidden contract `Product does not
  import the laboratory` with eight baselined edges; `#472`, `#474`, `#475` and `#477` removed
  them, and the contract now carries zero `ignore_imports`.
- **Git is not a backup of `data/`.** The handoff said so; on 2026-09-10 the main checkout's
  gitignored data roots were emptied during a worktree sweep, and the first backup with
  `platform.backup_recovery` was taken the same evening. No commit records the loss (it lives
  in the owner's session notes); `#476` is the guard it produced, keeping published ledger and
  scoreboard rows when the local ledger is empty.
- **Branch-scoped records go false at the merge.** The checklist, acceptance and handoff were
  written as one branch's state and were wrong at several lines within a day. Decisions belong
  here; local acceptance evidence stays in Git history, not in living documents.

## Verification

`git log --first-parent 0d9bd462..d31e64d0` lists every PR named above. `lint-imports`
proves the two contracts carry zero exceptions.
