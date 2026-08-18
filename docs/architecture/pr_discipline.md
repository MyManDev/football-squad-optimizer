# PR Discipline

How a change gets from an idea to `develop` without breaking a working, measured system, and
without three people colliding in the same files.

This is the working agreement. For the layer rules it enforces see
[dependency rules](dependency_rules.md); for who approves what, [ownership](ownership.md); for
the branch and gate mechanics, [branching](branching.md). The acceptance standard for a handoff
is unchanged and lives in `../handoff_acceptance_checklist.md` — 17 items with an explicit
acceptance rule. This document does not restate it.

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

Four today, five when `lint-imports` is wired in. All must pass on the delivering branch:

```bash
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m ruff format --check .
.venv/Scripts/python -m mypy
.venv/Scripts/python -m pytest
```

**Run the full `pytest`, not `-m "not slow"`.** The full suite is the merge gate, and the
marker split buys less than two minutes: measured on `b031ef1`, the full suite is 443 s and
`-m "not slow"` is 335 s. The eight `slow` tests are 0.4% of the 1,969 collected and 24% of the
wall clock, so the marks are well chosen — but 5 m 34 s is not a fast suite. The 37
`tests/integration` tests, including a full decision-chain rehearsal, are inside it, and
deselecting `slow` does not even avoid the session-scoped `baseline_result` fixture
(`tests/conftest.py:31-33`), which runs a CP-SAT solve regardless.

Use `-m "not slow"` for a quick local signal while iterating. Do not present it as having
tested the change. Details and the full timing table are in [branching](branching.md).

Note also that mypy checks only `src/squadopt` and ruff's `src` setting covers only
`src` and `tests`, so `scripts/` — 51 modules and 11,346 lines, holding most of the entry-point
logic — is outside two of the four gates. Treat script changes as unchecked and review them
accordingly.

## The live path

`live/`, `optimization/`, `prediction/` and `scenarios/` are the operational path. Any PR
touching them:

1. Runs the full suite, including the replay determinism tests in
   `tests/unit/test_live_recommendation.py`.
2. Runs **`test_the_recorded_gw1_replay_fingerprint_holds`**, which pins the opening-gameweek
   replay to recorded literals. If the fingerprint moved, either the change altered a live
   decision — say so explicitly in the PR and get the owner's agreement — or it is a bug.
3. Respects the freeze window in [ownership](ownership.md): no merges within 24 hours either
   side of a deadline.

### About the replay check

An earlier version of this agreement required verifying three replay hashes
(`2007677d`, `b367c98d`, `6b2c6024`) on every live-path PR. **Those values do not exist
anywhere in this repository** — not in `src/`, `scripts/`, `tests/`, `docs/` or `README.md`. The
only trace of the claim is a narrative aside in `../measurements_index.md` asserting the GW1
replay is byte-identical, with no hash, no command and no artifact. The determinism tests that
do exist compare two in-process runs and pin no literal, so they would pass even if every
number changed.

A gate nobody can evaluate is worse than no gate, because it reads as protection. The pinned
fingerprint test replaces it, and it lands in its own companion PR — so until that PR merges,
this section describes the intent and step 1 is the enforceable part.

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
- [ ] Four gates pass on the branch, full `pytest`.
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
