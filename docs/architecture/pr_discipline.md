# PR Discipline

How a change gets from an idea to `develop` without breaking a working, measured system, and
without three people colliding in the same files.

This is the working agreement. For the layer rules it enforces see
[dependency rules](dependency_rules.md); for who approves what, [ownership](ownership.md); for
the branch and gate mechanics, [branching](branching.md). The acceptance standard for a handoff
is unchanged and lives in `../handoff_acceptance_checklist.md`, an itemised list with an
explicit acceptance rule. This document neither restates it nor counts it; the file is the
count.

## One topic per pull request

The rule that does the most work:

- **A refactor PR never produces an artifact.** If a measurement number changed, the PR was not
  a refactor.
- **A measurement PR never moves a file.** If imports moved, the measurement is no longer
  comparable to the one before it.
- **A docs PR touches no source.**

The reason is reviewability, not tidiness. When a PR both moves code and writes numbers, "did
this change behaviour?" stops being answerable, and in this repository that question is the
whole point. Recent history shows the failure mode: one PR of 64 files and 346,000 insertions
mixing `live/`, `planning/`, `uncertainty/`, `experiments/` and `scripts/` cannot be reviewed as
one thing, however good each part is.

Target size is roughly 300 lines of reviewable change. Generated artifacts do not count toward
it; a 20,000-line JSON record is one artifact, not 20,000 lines of review.

## Moving code without breaking imports

When a symbol changes home:

1. The new location becomes the definition.
2. The old location re-exports it, so **no import breaks in the PR that moves it**.
3. A separate, later PR removes the re-export.

Re-exports live exactly one release. Longer, and they become permanent and the old boundary
never dies; shorter, and every move is a wide breaking change.

## The gates

Five gates are wired into CI. All must pass on the delivering branch:

```bash
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m ruff format --check .
.venv/Scripts/python -m mypy
.venv/Scripts/lint-imports
.venv/Scripts/python -m pytest -n auto --dist loadscope
```

**Run the full suite in parallel, not `-m "not slow"`.** The full suite is the merge gate, and
the marker split no longer buys anything: measured on `43b0d7f`, the parallel full suite is
**121 s** while the serial run is 453 s and deselecting `slow` still leaves ~331 s. So the
fast-suite question is settled by parallelism rather than by marks — the whole gate now costs
less than a third of what the subset used to. The nine `slow` tests are 0.4% of the 2,563
collected and 27% of the serial wall clock; the marks are reasonable, but 21 of the 30 costliest
items carry no mark at all (#230), so the subset was never the fast suite it looked like.

Use a single `pytest path::test` for a quick local signal while iterating — `-n auto` is not in
`addopts`, so that stays serial and starts instantly. Do not present a subset as having tested
the change. Details and the full timing table are in [branching](branching.md).

Note also that mypy checks only `src/squadopt` and ruff's `src` setting covers only
`src` and `tests`, so `scripts/` — 51 modules and 11,346 lines, holding most of the entry-point
logic — is outside two of the five gates. Treat script changes as unchecked and review them
accordingly.

## The live path

`live/`, `optimization/`, `prediction/` and `scenarios/` are the operational path. Any PR
touching them:

1. Runs the full suite, including the replay determinism tests in
   `tests/unit/test_live_recommendation.py`.
2. Runs **`test_the_recorded_gw1_replay_decision_holds`**
   (`tests/unit/test_live_recommendation.py`), which pins the opening-gameweek decision to
   recorded literals — the projection digest, the fifteen squad ids, the starting eleven, the
   bench, the captain, the cost and the score. If it moves, either the change altered a live
   decision — say so explicitly in the PR, get the live-path owner's agreement, and update the
   literals in the same commit — or it is a bug.
3. Respects the freeze window in [ownership](ownership.md): no merges within 24 hours either
   side of a deadline.

### About the replay check

An earlier version of this agreement required verifying three replay hashes
(`2007677d`, `b367c98d`, `6b2c6024`) on every live-path PR, and **those values existed nowhere
in this repository** — they were local Windows-only digests recorded in a pull-request body and
never committed. The determinism tests that existed compared two in-process runs and pinned no
literal, so they would have passed even if every number changed.

That is closed. The pinned test named above landed in #113, and #116 then had to move its
literal for a real reason: the first Linux CI run showed the digest was platform-dependent,
because `to_csv` defaulted its line terminator to `os.linesep`. The gate caught a determinism
defect on its first outing, which is the argument for having it.

**This section is itself the standing example of the failure it describes.** Between the plan
and the implementation the test was renamed, and step 2 above kept pointing at
`test_the_recorded_gw1_replay_fingerprint_holds`, which never existed — so for a while this
document named an unrunnable gate while explaining why unrunnable gates are worse than none.
If you change the name of a pinned test, change it here in the same commit.

## Working zones, and how to not collide

Zones are in [ownership](ownership.md). In practice:

- Stay in your zone. A change that needs someone else's zone is a conversation first, not a
  larger PR.
- Shared boundaries — `contracts/`, `data/schema.py`, `optimization/config.py`, `backtest/` —
  need one approving review from each of the other two roles.
- If two people must work in the same area at once, split by file, not by function, and say so
  before starting.

## Before opening a PR

- [ ] One topic. No artifacts in a refactor; no moves in a measurement.
- [ ] Five gates pass on the branch, including full `pytest` and `lint-imports`.
- [ ] Layer rules respected; no new entry in the dependency baseline.
- [ ] Symbols that moved are re-exported from their old location.
- [ ] Live-path changes carry the replay check and are outside the freeze window.
- [ ] New committed artifact has a row in `../measurements_index.md`
      ([ADR 0003](decisions/0003-measurement-artifacts.md)).
- [ ] Conventional Commits subject. No AI attribution and no `Co-Authored-By` trailer.
- [ ] The PR body says what changed, what it deliberately did not change, and how it was checked.

## What a PR body should say

The commit messages in this repository are already unusually good — they say what changed, what
was measured, and what stayed fixed. Keep that. The one thing to add explicitly is what the
change **did not** touch, because on a system where behaviour is the contract, the absence of
change is half the claim.
