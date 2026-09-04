# ADR 0002 — Where contract versions and fingerprints live

- **Status:** accepted
- **Date:** 2026-08-18
- **Deciders:** all three owners
- **Related:** [ADR 0001](0001-modular-monolith.md), [dependency rules](../dependency_rules.md)

## Context

This project's central discipline is that a recorded number can be reproduced. That works
because almost every configuration carries a version string and a fingerprint, and artifacts
record both. The mechanism is genuinely load-bearing — `issue43_handoff_acceptance.md:45`
accepts a declaration only because re-running it reproduced the committed JSON byte for byte.

The mechanism has grown without a home. Measured on `b031ef1`:

- **79 module-level version constants across 50 modules.** No registry, no shared type; each is
  a bare `str` or `Final[str]` declared next to whatever consumes it.
- **35 modules import `hashlib`**, each computing its own digest. There is no shared fingerprint
  primitive. The only fingerprint helper reused across a package boundary by a public name is
  `objective_coefficient_fingerprint` (`optimization/coefficients.py:63`), with a single
  external importer.
- **14 independently implemented `configuration_fingerprint` properties.**
- **Duplicated literals.** The same version string is declared in several modules with no shared
  constant:

  | Literal | Sites |
  | --- | --- |
  | `single_gameweek_realized_squad_points_v1` | `backtest/candidate_residuals.py:33`, `backtest/policy_evaluation.py:46`, `backtest/production_benchmark.py:129`, `bayesopt/evaluation.py:27`, `experiments/policy_objective.py:43` |
  | `linear_fixture_count_scaling_v1` | `backtest/horizon_decay.py:50`, `live/horizon.py:74` |
  | `form_window_v1` | `backtest/policy_evaluation.py:47` as `FORM_WINDOW_MAPPING_VERSION`, `prediction/factors.py:10` as `FEATURE_GENERATION_CONTRACT_VERSION` |

The last row is the one that should worry us. The same contract identity is asserted under two
different names in two different layers. Nothing detects it if one of them is bumped and the
other is not, and the artifacts would then claim two versions of one thing while looking
perfectly self-consistent.

## Decision

**Contract versions and fingerprint primitives belong in `contracts`. Everything else about a
contract stays with the layer that owns it.**

Concretely:

1. **`contracts` holds the vocabulary and the primitives**, and imports nothing from
   `squadopt`:
   - `Position`, `POSITIONS`, `REQUIRED_COLUMNS`, `sort_players_by_id`
   - the fingerprint primitive that the 35 local `hashlib` uses converge on — one canonical
     "hash this mapping deterministically" function, so digests are comparable by construction
   - a registry of contract-version identities: one name per contract, defined once

2. **A contract version is declared exactly once.** Where two modules need the same identity,
   both import it from the registry. The three duplicated literals above are the first
   conversions.

3. **`Position` stays a `Literal`.** It is `Literal["GK", "DEF", "MID", "FWD"]` today
   (`optimization/config.py:12`). Turning it into an `Enum` would change behaviour at every one
   of its 20 import sites, alter how positions serialise into artifacts, and therefore change
   recorded fingerprints. A type alias is sufficient for the checking we get from mypy strict.
   Not worth the blast radius.

4. **Source vocabularies are named as such.** `live/rules.py:29` defines a second
   `POSITIONS = ("GKP", "DEF", "MID", "FWD")`. That is not a bug — it is the FPL API's own
   vocabulary, used to validate the scoring table the capture publishes, and it is mapped to
   canonical `GK` by `POSITION_ALIASES` at `data/schema.py:340`. But two constants with the same
   name and different values in one codebase is a trap. It becomes `FPL_POSITION_CODES`. The
   rule: an external vocabulary is named after its source, never after the concept it maps to.

5. **Bumping a version is a deliberate, recorded act.** A version changes only when the
   contract's meaning changes, in a PR that says so, and the artifacts that assert the old
   version are either regenerated or explicitly left as historical records. Renaming a field or
   reformatting output changes the fingerprint, so it is a version change even when it feels
   cosmetic.

## Why not the alternatives

**Leave versions where they are.** They are readable next to their consumer, and locality is a
real virtue. But it has already produced one contract identity under two names, and there is no
mechanism that would ever tell us. Locality is worth less than a single definition here.

**One central versions module listing all 79.** Rejected. It would become a file every layer
edits for every change, its diff would be permanent merge-conflict territory, and it separates
the version from the thing it versions for no gain. Only *shared* identities move; a version
used in exactly one module stays there.

**A version object with parsing and comparison.** Rejected as unnecessary. Nothing in the system
compares versions for ordering — they are identities, matched exactly. A string is the right
type, and `Final` already gives the immutability we rely on.

## Consequences

**Accepted:**

- `contracts` gains the fingerprint primitive, which makes it slightly more than pure
  vocabulary. The boundary is: it may contain deterministic pure functions with no `squadopt`
  imports, and nothing that makes a decision.
- Converging 35 local `hashlib` call sites onto one primitive risks changing digests. Any
  conversion that changes a recorded fingerprint must either reproduce the old bytes exactly or
  be treated as a version bump under rule 5. Most call sites are expected to be
  byte-compatible; that has to be demonstrated per site, not assumed.
- Renaming `live/rules.py`'s `POSITIONS` touches the live path and so carries the replay check
  from [PR discipline](../pr_discipline.md).

**Gained:**

- One contract, one identity. The `form_window_v1` double-naming becomes impossible to
  reintroduce silently.
- `data` and `prediction` stop importing `optimization`, which is two of the three remaining
  layering violations.

## Verification

```bash
grep -rcE '^[A-Z_]*VERSION[A-Z_]*(: *Final)? *=' src/squadopt --include='*.py' | awk -F: '$2>0' | wc -l
grep -rhoE '^[A-Z_]+(: *Final)? *= *"[a-z0-9_]+"' src/squadopt | sed -E 's/.*= *"//; s/"//' | sort | uniq -c | awk '$1>1'
```

The first counts the modules holding version constants (50 today). The second lists literals
declared in more than one place — the target is that no *contract-version* literal appears
twice. Note the second command also surfaces harmless duplicated enum-like strings
(`blank`, `no_record`, `in_season_history`); those are values, not contract identities, and are
not in scope.
