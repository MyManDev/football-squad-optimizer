# Contributing

The working agreements live under [`docs/architecture/`](docs/architecture/). Start here:

| Question | Document |
| --- | --- |
| What is in the package, and what depends on what? | [system map](docs/architecture/system_map.md) |
| May this module import that one? | [dependency rules](docs/architecture/dependency_rules.md) |
| Who approves this change? | [ownership](docs/architecture/ownership.md) |
| Where does runtime/platform work begin? | [platform and runtime boundary](docs/architecture/platform_runtime.md) |
| Which branch do I target, and what must pass? | [branching](docs/architecture/branching.md) |
| How do I scope and open the PR? | [PR discipline](docs/architecture/pr_discipline.md) |
| Why is it built this way? | [decisions](docs/architecture/decisions/) |
| Is this handoff acceptable? | [acceptance checklist](docs/handoff_acceptance_checklist.md) |
| What has been measured, and what did it find? | [measurements index](docs/measurements_index.md) |

## The short version

1. Branch from `develop`. Pull requests target `develop`; `main` is the release pointer.
2. **One topic per PR.** A refactor never produces an artifact; a measurement never moves a
   file; a docs PR touches no source.
3. All gates pass on your branch before review:

   ```bash
   .venv/Scripts/python -m ruff check .
   .venv/Scripts/python -m ruff format --check .
   .venv/Scripts/python -m mypy
   .venv/Scripts/python -m pytest
   ```

   Run the full `pytest`. `-m "not slow"` deselects 8 of 1,969 tests and is a local convenience,
   not a substitute.
4. Stay in your zone; shared boundaries need all three owners.
5. Live-path changes carry the replay check and respect the deadline freeze window.

## Setup

Python 3.11 or newer:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[api,dev]"
```

The test suite is entirely synthetic and offline — it needs neither the historical archive nor
the network.

## Commit messages

Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`), imperative subject, and a
body that says what changed, what was measured, and **what deliberately did not change**.

Do not add AI attribution of any kind: no `Co-Authored-By` trailer, no assistant name in
commits, PR bodies, issues or files.
