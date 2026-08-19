# Branching and Protection

Where work lands, what must pass before it lands, and what `main` is for.

## The trunk

**`develop` is the trunk. `main` is the release pointer.**

Every pull request targets `develop`. `main` advances only on a deliberate release merge from
`develop` — it is the stable ref for the live season, so that "what is running" and "what is
being built" are two different questions with two different answers.

This is now a description as well as a decision. The first release merge happened in #130,
tagged `v2026-27.gw01`, so `main` carries the opening-season pointer instead of an empty tree.
GitHub's default branch is `develop`, which is where work lands.

## Protection

Both branches are protected. Required on `develop`:

- the five gates below, as required status checks;
- one approving review, and for shared boundaries one from each of the other two roles per
  [ownership](ownership.md);
- no force-push, no deletion;
- branches up to date with `develop` before merge.

`main` additionally allows no direct pushes at all: it moves by release merge only.

`delete_branch_on_merge` should be on and **is not** — `gh api repos/:owner/:repo` reports
`false`, and stale heads keep accumulating. Because pull requests are squash-merged, git cannot
prove a branch was merged even when its content is in `develop`, so do not prune with
`git branch --merged`: it reports almost nothing as merged and the reachability test is
misleading rather than conservative. Prune by whether the pull request is closed.

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

**The interpreter versions disagree.** `requires-python = ">=3.11"`, ruff's
`target-version = "py311"`, mypy's `python_version = "3.13"`, and the development venv runs
3.11.0. Type checking therefore assumes a newer language than the code runs on. Pick one, or
run a matrix, and make the three settings agree either way.

`constraints.txt` now pins the measurement environment and the 3.13 CI job installs against
it, so that half is closed. One gap remains: a dependency added to `pyproject.toml` is not
automatically added to `constraints.txt`, and `scipy` arrived that way in #139 — declared as a
runtime dependency, pinned in `constraints.txt`, but the two are kept in step by hand. A
declared dependency missing from the pinned environment would make "the environment that
produced the committed artifacts" untrue without failing anything.

## Branch names

`feature/*`, `fix/*`, `docs/*`, `chore/*`, `test/*`. Commits follow Conventional Commits with
the PR number appended by the squash merge — the convention every one of the 90 commits already
follows, now written down.

## Verification

```bash
gh api repos/:owner/:repo --jq '{default_branch, delete_branch_on_merge}'
gh api repos/:owner/:repo/branches/develop/protection
```

Measured on 2026-08-19, `develop` protection is **partly** what this document asks for:

| Setting | Asked | Actual |
| --- | --- | --- |
| required status checks | the five gates | `gates (py3.11)`, `gates (py3.13)` — the `web` job is not required |
| `strict` (branch up to date) | yes | `true` |
| approving reviews | one, and one per other role on shared boundaries | **`0`** |
| `require_code_owner_reviews` | implied by the ownership table | **`false`** |
| `enforce_admins` | yes | **`false`** |
| `delete_branch_on_merge` | on | **`false`** |

So `.github/CODEOWNERS` is advisory: it neither requests nor requires a review, and the
ownership table it was derived from is not mechanically enforced. Twenty-one pull requests
merged on 2026-08-19 with zero required approvals. Closing that is a protection-settings
change, not a code change, and it belongs to the core-architecture owner.
