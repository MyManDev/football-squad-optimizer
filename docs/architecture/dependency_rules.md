# Dependency Rules

The one-directional order every import inside `squadopt` must respect, the exceptions that
exist today, and the rule for changing either. This document is the contract that
`lint-imports` enforces in CI and review.

For what the graph actually looks like right now, see [system map](system_map.md). For why
the shape is a single layered package, see [ADR 0001](decisions/0001-modular-monolith.md).
For the boundary above the application layer, see
[platform and runtime boundary](platform_runtime.md).

## The order

A package may import anything **below** it and nothing at or above it.

```
contracts
  data
    features
      prediction
        optimization
          evaluation
            uncertainty
              scenarios
                risk
                  planning
                    bayesopt
                      preflight
                        recalibration
                          backtest
                            experiments
                              live
                                application
                                  platform
                                    api / entry points
```

`application`, `platform`, and the optional `api` adapter now exist and are enforced as the
three highest package layers in `pyproject.toml`. `contracts` does not exist yet; it is in the
order so that when it is built there is no argument about where it goes. `contracts` depends
on nothing; `application` may reach everything below it; and `platform` may consume
application contracts without allowing HTTP, persistence, queue, authentication, or
deployment concerns to flow back into them. `api` is the concrete FastAPI entry point and may
consume `platform` and `application` public contracts. Other entry points mean CLI, workers,
schedulers, and script shells; that remains an architectural role rather than one proposed
package.

The general layers contract permits a high layer to import any lower layer. The API has a
second, stricter contract: `squadopt.api` may reach engine packages only indirectly through
the public `platform` and `application` boundaries. A new direct API import from `live`,
`optimization`, `prediction`, `planning`, `scenarios`, or any other engine package fails
`lint-imports`.

### Why this order and not the obvious one

The first draft of this order grouped the packages by what they are about, which reads better
and does not work. Three groupings had to be broken, each because the code already says
otherwise:

| Tempting grouping | Why it fails |
| --- | --- |
| `evaluation` above `uncertainty`/`scenarios`/`risk` | `uncertainty` imports `EvaluationFold` three times (`adaptive.py:16`, `calibration.py:16`, `fixture_folds.py:17`) and `risk` once (`evaluation.py:9`). Scoring a fold is more primitive than describing its spread, so `evaluation` goes below. |
| `{uncertainty, scenarios, risk}` as one tier | `risk` imports `uncertainty` three times (`config.py:13`, `evaluation.py:29`, `optimizer.py:20`). Risk is built on top of spread, not beside it. |
| `{experiments, bayesopt, recalibration, preflight}` as one tier | Four separate edges cross it: `experiments` to `bayesopt` (4), `backtest` to `bayesopt` (1), `backtest` to `preflight` (1), `experiments` to `preflight` (1). `bayesopt` is in fact a pure leaf and `preflight` only imports `data`, so both belong far lower. |

Choosing the order above instead of the thematic one takes the violation count from **16
imports across 9 pairs** to **5 imports across 3 pairs** without moving a single line of code.
That is the whole point of writing the order down before starting the migration: most of what
looked like technical debt was a mis-drawn diagram.

### Where the order is genuinely free

Some packages are independent of each other and their relative position is arbitrary. Do not
read meaning into it, and do not "fix" it:

- `bayesopt` imports no other subpackage at all. It could sit immediately above `contracts`.
- `preflight` imports only `data`.
- `recalibration` imports `data`, `features` and `scenarios`, so it needs to be above
  `scenarios` but is otherwise unconstrained.
- `scenarios` does not import `uncertainty`, and `planning` imports only `optimization`.

If a future import makes one of these positions load-bearing, say so here at the same time.

## The exceptions that exist today

Five import statements violate the order. They are listed exhaustively, they are the
`lint-imports` baseline, and **the list may only get shorter**.

| # | Edge | Imports | Sites | Closes with |
| --- | --- | --- | --- | --- |
| 1 | `data` to `optimization` | 2 | `data/schema.py:19`, `data/schema.py:20` | `contracts` |
| 2 | `prediction` to `optimization` | 1 | `prediction/integration.py:15` | `contracts` |
| 3 | `backtest` to `experiments` | 2 | `backtest/production_benchmark.py:57`, `:58` | `statistics` and `PromotionPolicy` moving to `evaluation` |

Both remedies are already planned work, and between them they take the baseline to zero. No
other package move is required to reach a clean contract — in particular, narrowing the wide
barrels (`experiments` re-exports 82 names, `live` 79, `data` 68) is a separate quality
concern and not a prerequisite.

### What goes in `contracts`

Only vocabulary. Nothing that computes a decision, and nothing that imports anything else in
`squadopt`.

- `Position` (`optimization/config.py:12`) and `POSITIONS` (`:13`)
- `REQUIRED_COLUMNS` (`optimization/validation.py:15`), the projection contract
- `sort_players_by_id` (`optimization/coefficients.py:46`) — nine lines whose docstring calls
  it "the stable player ordering used by the model and its fingerprints"; canonical ordering
  is a contract even though it is a function
- the identity and fingerprint primitives, and the contract-version registry, per
  [ADR 0002](decisions/0002-contract-versioning.md)

`contracts` is a shared boundary in [ownership](ownership.md): changes need all three owners.
That is deliberate friction. A module every layer depends on is the one place where a casual
edit is most expensive, and it is the natural dumping ground for anything that is awkward to
place. If a symbol is not vocabulary that at least two layers need, it does not go here.

## Rules for changing this document

1. **The baseline may only shrink.** A PR that adds a violating import is rejected, not
   baselined. If the import is genuinely necessary, the order is wrong and this document
   changes first, in its own PR, with all three owners agreeing.
2. **Re-exports live exactly one release.** When a symbol moves, the old location keeps
   re-exporting it so no import breaks in the same PR that moves it. The re-export is removed
   in a later, separate PR. This is what makes each migration step reviewable in isolation.
3. **Boundary files change only by joint approval** — see [ownership](ownership.md).
4. **The order is a claim about the code, so it is verified, not trusted.** Any change here
   comes with the regenerated numbers.

## Verification

CI runs `lint-imports` against the contract in `pyproject.toml`. `import-linter` lists layers
**highest first**, which is the reverse of the order written at the top of this document. Its
current top is:

```toml
[tool.importlinter]
root_package = "squadopt"

[[tool.importlinter.contracts]]
name = "Layered architecture"
type = "layers"
layers = [
    "api",
    "platform",
    "application",
    "live",
    "experiments",
    "backtest",
    "recalibration",
    "preflight",
    "bayesopt",
    "planning",
    "risk",
    "scenarios",
    "uncertainty",
    "evaluation",
    "optimization",
    "prediction",
    "features",
    "data",
]
```

The excerpt abbreviates the fully qualified names used by `pyproject.toml`, which is the
executable source of truth. `squadopt.api` is listed above `squadopt.platform`, which is listed
above `squadopt.application`; the API therefore cannot be imported back into runtime or
application code. The platform's first package contract is the versioned run context and
manifest. The five baseline violations are expressed as
`ignore_imports` entries, one per statement, each carrying the issue that will remove it — not
as a blanket exemption for the package pair, so a *new* bad import between the same two
packages still fails.

A separate forbidden-import contract lists `squadopt.api` as its source, every engine package
below `application` as forbidden, and permits indirect imports. That last setting is
deliberate: application services may compose the engine, while HTTP modules may not bypass
those services.

Last measured against `b031ef1` (PR #110).
