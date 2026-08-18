# Branching and Protection

Where work lands, what must pass before it lands, and what `main` is for.

## The trunk

**`develop` is the trunk. `main` is the release pointer.**

Every pull request targets `develop`. `main` advances only on a deliberate release merge from
`develop` — it is the stable ref for the live season, so that "what is running" and "what is
being built" are two different questions with two different answers.

This is a decision, not a description. Today `main` still sits at the initial commit while all
90 commits live on `develop`, and `main` is GitHub's default branch — so a fresh clone lands on
an empty repository. The first release merge fixes that. Until it happens, treat `main` as
unusable rather than as a baseline.

## Protection

Both branches are protected. Required on `develop`:

- the five gates below, as required status checks;
- one approving review, and for shared boundaries one from each of the other two roles per
  [ownership](ownership.md);
- no force-push, no deletion;
- branches up to date with `develop` before merge.

`main` additionally allows no direct pushes at all: it moves by release merge only.

`delete_branch_on_merge` is on. Without it stale heads accumulate — 88 of them exist today,
because pull requests are squash-merged and git therefore cannot prove the branch was merged
even when its content is in `develop`. Do not try to prune them with
`git branch --merged`; it will report almost nothing as merged. Prune by whether the PR is
closed.

## The gates

Four exist today and are documented in three places — `../../README.md` under Quality checks,
`../handoff_acceptance_checklist.md:36` item 16, and `../recalibration_runbook.md`. All four are
currently manual PowerShell invocations that nothing enforces:

| # | Gate | Command |
| --- | --- | --- |
| 1 | lint | `python -m ruff check .` |
| 2 | format | `python -m ruff format --check .` |
| 3 | types | `python -m mypy` |
| 4 | tests | `python -m pytest` |
| 5 | imports | `lint-imports` |

The fifth is new: the layering contract from [dependency rules](dependency_rules.md). It is
listed here so the target is five, but it is not a gate until the architecture/CI owner adds
`import-linter` and the contract to `pyproject.toml`.

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
for the architecture/CI owner. The numbers above are the first test-suite timings recorded for
this repository; regenerate them with `pytest --durations=15` rather than trusting this table
after the suite grows.

**The interpreter versions disagree.** `requires-python = ">=3.11"`, ruff's
`target-version = "py311"`, mypy's `python_version = "3.13"`, and the development venv runs
3.11.0. Type checking therefore assumes a newer language than the code runs on. Pick one, or
run a matrix, and make the three settings agree either way.

There is also no lockfile or constraints file anywhere, and every lock line in `.gitignore` is
commented out, so dependency ranges resolve freely — `mypy>=1.14,<3` currently resolves to
2.3.0 and `pandas>=2.2.3,<3.1` to 3.0.5. CI without pinning will drift and produce failures
nobody changed.

## Branch names

`feature/*`, `fix/*`, `docs/*`, `chore/*`, `test/*`. Commits follow Conventional Commits with
the PR number appended by the squash merge — the convention every one of the 90 commits already
follows, now written down.

## Verification

```bash
gh api repos/:owner/:repo --jq '{default_branch, delete_branch_on_merge}'
gh api repos/:owner/:repo/branches/develop/protection
```

Both should reflect what this document says. Today neither does — no protection exists on
either branch, and `delete_branch_on_merge` is false. That is the gap Stage 1 closes.
