# Branching and Protection

Where work lands, what must pass before it lands, and what `main` is for.

## The trunk

**`develop` is the trunk. `main` is release history.**

Every pull request targets `develop`. `main` advances only on a deliberate release merge from
`develop`. The first release merge happened in #130, tagged `v2026-27.gw01`, so `main`
carries the opening-season pointer instead of an empty tree. The live static site is the
latest successful immutable `site-...` deployment tag, so production may deliberately lag
`main`; the deployment Actions summary answers "what is running", while `main` answers
"what is releasable". GitHub's default branch is `develop`, which is where work lands.

## Protection

Both branches are protected. Current required checks on `develop` are the two Python gate
contexts, `gates (py3.11)` and `gates (py3.13)`, with strict up-to-date branches. Each context
runs the five Python gates below. The web job also runs in CI but is not currently a protected
required context.

The required approving review count is zero, matching the team's check-then-squash workflow.
Force-push and branch deletion are disabled. `main` uses the same two required contexts and
normal changes reach it through a deliberate release pull request from `develop`.

`main` additionally allows no direct pushes at all: it moves by release merge only.

`delete_branch_on_merge` is deliberately false. Feature branches are retained after squash
merge under the current team policy; do not prune them merely because their pull request
closed.

## The gates

Five exist today. The first four are also documented in `../../README.md` under Quality checks,
`../handoff_acceptance_checklist.md:36` item 16, and `../recalibration_runbook.md`; the fifth is
the layering contract in [dependency rules](dependency_rules.md). CI enforces all five:

| # | Gate | Command |
| --- | --- | --- |
| 1 | lint | `python -m ruff check .` |
| 2 | format | `python -m ruff format --check .` |
| 3 | types | `python -m mypy` |
| 4 | tests | `python -m pytest` |
| 5 | imports | `lint-imports` |

`pyproject.toml` is the executable source of truth for the import contract, and
`.github/workflows/ci.yml` runs `lint-imports` alongside the other four gates.

### Two things to know before wiring these into CI

**The fast suite is not fast yet.** Measured on `b031ef1`, on one developer machine
(Python 3.11.0, 1,969 collected tests):

| Suite | Command | Tests run | Wall clock |
| --- | --- | --- | --- |
| full | `pytest` | 1,968 (1 skipped) | **443 s** (7 m 23 s) |
| "fast" | `pytest -m "not slow"` | 1,960 (8 deselected) | **335 s** (5 m 34 s) |

So the eight `slow` tests are 0.4 per cent of the count and 24 per cent of the wall clock —
the marks are well chosen. But deselecting them still leaves **5 m 34 s**, so `-m "not slow"`
is not a fast suite in any useful sense, and wiring PR gates to it buys under two minutes.

Where the remaining time goes: the 37 `tests/integration` tests are inside the "fast" suite;
the session-scoped `baseline_result` fixture (`tests/conftest.py:31-33`) runs a full CP-SAT
solve regardless of markers; CP-SAT is deliberately single-threaded for determinism with a
10 s default budget per solve; and the solver-dense files (`test_evaluator.py`,
`test_optimizer.py`, `test_risk_optimizer.py`, `test_bayesian_optimization.py`,
`test_multi_gw_rehearsal.py`) carry no marks at all. The costliest individual tests are the
rank-objective and scenario searches at 8–21 s each.

A genuinely fast suite needs either more marks, parallelism (`pytest-xdist` — note the
determinism constraint applies within a solve, not across tests), or both. Those are choices
for the core-architecture owner. The numbers above are the first test-suite timings recorded for
this repository; regenerate them with `pytest --durations=15` rather than trusting this table
after the suite grows.

**Interpreter coverage is deliberate.** `requires-python = ">=3.11"` and ruff target Python
3.11, while mypy models Python 3.13. CI therefore runs both Python 3.11 (declared dependency
ranges) and 3.13 (the pinned measurement environment in `constraints.txt`).

One gap remains: a dependency added to `pyproject.toml` is not automatically added to
`constraints.txt`, and `scipy` arrived that way in #139 — declared as a runtime dependency,
pinned in `constraints.txt`, but the two are kept in step by hand. A declared dependency
missing from the pinned environment would make "the environment that produced the committed
artifacts" untrue without failing anything.

## Branch names

`feature/*`, `fix/*`, `docs/*`, `chore/*`, `test/*`. Commits follow Conventional Commits with
the PR number appended by the squash merge — the convention the history already follows, now
written down. Check it against the log (`git log --oneline`) rather than against a commit count
recorded here.

## Verification

```bash
gh api repos/:owner/:repo --jq '{default_branch, delete_branch_on_merge}'
gh api repos/:owner/:repo/branches/develop/protection
```

Read the answer rather than a copy of it. An earlier draft of this section pasted the six
measured values into a table, which is the same mistake the rest of this pull request exists to
undo: a number committed to a document is right on the day it is written and silently wrong
afterwards, and nothing fails when it drifts. What is worth writing down is how to interpret
whatever the command prints.

**The rule.** Every requirement listed under [Protection](#protection) is asked of the settings.
Where the settings do not supply one, the requirement still stands as an agreement — it is
simply unenforced, and an unenforced agreement is kept by people or not at all.

**How to tell which regime you are in.** Two fields decide whether the ownership table has any
mechanical force:

- `required_pull_request_reviews.required_approving_review_count` — if this is `0`, a pull
  request can merge with no review at all, and GitHub reporting a branch as `CLEAN` means only
  that nothing blocks the button, **not** that anyone approved it.
- `required_pull_request_reviews.require_code_owner_reviews` — if this is `false`,
  `.github/CODEOWNERS` neither requests nor requires a review, so the shared-boundary rule
  (one approval from each of the other two roles) is convention rather than a gate.

While both hold, treat a shared-boundary merge as needing sign-off you have to go and ask for,
and record it in the pull request so the agreement leaves a trace the settings do not.

Two further readings worth knowing. `required_status_checks.contexts` lists which checks
actually block: a job that runs on every pull request but is absent from that list can be red
without stopping a merge. And `delete_branch_on_merge` governs cleanup — while it is off, stale
heads accumulate, and because pull requests are squash-merged git cannot prove a branch was
merged even when its content is in `develop`. Do not prune with `git branch --merged`: it
reports almost nothing as merged, so the reachability test misleads rather than errs on the safe
side. Prune by whether the pull request is closed.

Closing any of these gaps is a protection-settings change, not a code change, and it belongs to
the core-architecture owner.

For the record, as history rather than as current state: on 2026-08-19 twenty-one pull requests
merged with zero required approvals, which is what prompted this section to be written down.
