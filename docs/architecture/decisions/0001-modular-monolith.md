# ADR 0001 — One layered package, enforced by a linter

- **Status:** accepted
- **Date:** 2026-08-18
- **Deciders:** all three owners
- **Supersedes:** nothing. First architecture decision recorded for this repository.

## Context

The system works and is measured. Ninety commits have produced 132 modules under
`src/squadopt`, 51 entry-point scripts, 1,969 tests and 41 recorded real-data measurements.
What it does not have is any statement of its own shape: no architecture document, no
dependency rule, no ownership table, and nothing that fails when a boundary is crossed. The
only tracked dotfile in the repository is `.gitignore`.

The cost of that shows up as a small number of imports pointing the wrong way — `data`
reaching up into `optimization` for its own vocabulary, `backtest` and `experiments` importing
each other — and as a large number of decisions that live only in people's heads. Three people
now work in the same tree, and a fourth surface (CI and packaging) is about to be taken over by
someone who did not write any of it.

Two questions had to be answered together: what shape are we aiming at, and what stops us
drifting off it.

## Decision

**One installed package with a strict one-directional layer order, enforced in CI by
`import-linter` as a fifth quality gate.**

Not a split into several distributable packages. Not a plugin architecture. The layers are
internal to `squadopt`, expressed as a `layers` contract in `pyproject.toml`, and the order is
recorded in [dependency rules](../dependency_rules.md).

Two packages are added to the order before they exist, so there is no argument later about
where they go: `contracts` at the bottom, depending on nothing, holding the vocabulary every
layer shares; and `application` above `live`, holding the workflows that the 51 scripts
currently inline.

The migration is a sequence of small behaviour-preserving pull requests. When a symbol moves,
its old location re-exports it for exactly one release so that no import breaks in the same PR
that moves it.

## Why not the alternatives

**Split into separate packages.** Real enforcement — you cannot import what you did not
install. But it prices in versioning, release coordination and cross-repository changes for a
codebase three people change several times a day, and it would make the measurement work
(which legitimately reaches across almost every layer) into a dependency-management problem.
The boundaries we need are internal; buying them with distribution is overpaying.

**Write the rules down and rely on review.** Cheapest, and it is what happens today. It
produced the reverse dependency in `data/schema.py` even though that module's own docstring
says the vocabulary belongs somewhere neutral. Writing a rule nobody checks is how the
`data_followups.md` proposal for a contracts module has sat unimplemented. If the rule matters,
it fails the build.

**Rewrite into the target layout in one move.** Rejected outright. The system's value is that
it is measured — 41 artifacts assert specific numbers, several pinned by tests. A large
simultaneous move makes every one of those a suspect, and makes "did we change behaviour?"
unanswerable. Behaviour-preserving steps keep that question cheap.

## The order, and the correction that made this decision affordable

The first draft of the layer order grouped packages by subject matter: scoring above spread,
the three spread packages as one tier, the four search-and-gate packages as one tier. It reads
well and it is not satisfiable — the code already says otherwise in three places:

- `uncertainty` imports `EvaluationFold` three times and `risk` once, so `evaluation` must sit
  *below* them, not above.
- `risk` imports `uncertainty` three times, so those two cannot share a tier.
- `experiments` imports `bayesopt` four times, `backtest` imports `bayesopt` and `preflight`
  once each, and `experiments` imports `preflight` once — so those four cannot share a tier
  either. `bayesopt` turns out to import no other subpackage at all.

Measured against the code, the thematic order leaves **16 violating imports across 9 package
pairs**. The corrected order in [dependency rules](../dependency_rules.md) leaves **5 across
3**, without moving a single line.

That difference is the most important thing in this ADR. Eleven of the sixteen "violations"
were an artifact of drawing the diagram by intuition rather than by measurement. The remaining
five are two real problems — the misplaced shared vocabulary, and the measurement cycle — both
already planned. So the migration to a clean contract is two focused pull requests, not a long
grind through every package.

A direct consequence: narrowing the wide barrels (`experiments` re-exports 82 names, `live` 79,
`data` 68) is **not** a prerequisite for a green contract. It stays worth doing for
readability, and it is no longer on the critical path.

## Consequences

**Accepted:**

- A fifth gate to keep green, and a baseline file that must only ever shrink.
- Some churn from the re-export-for-one-release rule: every move is two PRs, not one.
- `contracts` becomes a shared boundary needing three approvals, which is deliberate friction
  on the module most likely to attract unrelated additions.
- The order contains positions that are arbitrary because the packages are independent
  (`bayesopt`, `preflight`, `recalibration`). Someone will eventually "fix" one of these unless
  the freedom is documented — it is, in [dependency rules](../dependency_rules.md).

**Gained:**

- "Who approves this, and where does it go?" is answerable from one page.
- New imports in the wrong direction fail the build instead of being discovered later.
- The `backtest` and `experiments` cycle stops being a trap. It currently survives only because
  `backtest/__init__.py` happens not to import `production_benchmark`; adding it to that barrel
  would raise `ImportError`.

**Not addressed here:** the ledger's crash-safety, the absence of atomic writes anywhere in the
codebase, and the fact that the "fast" test suite is 335 s against the full suite's 443 s. Those
are real and separately owned; see [branching](../branching.md) for the measured test-suite
timings and the live-path owner for the ledger.

## Verification

The claim that the corrected order leaves five violations is checkable, and the method is in
[system map](../system_map.md). If a reviewer reruns it and gets a different answer, the
documents are wrong and this ADR's central argument needs re-examining.
