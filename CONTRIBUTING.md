# Contributing

The [architecture overview](ARCHITECTURE.md) describes the shape of the system. The working
agreements live under [`docs/architecture/`](docs/architecture/README.md). Start here:

| Question | Document |
| --- | --- |
| What is in the package, and which ring is each part in? | [architecture overview](ARCHITECTURE.md) and [system map](docs/architecture/system_map.md) |
| May this module import that one? | [dependency rules](docs/architecture/dependency_rules.md) |
| Who approves this change? | [ownership](docs/architecture/ownership.md) |
| Where does runtime/platform work begin? | [platform and runtime boundary](docs/architecture/platform_runtime.md) |
| Which branch do I target, and what must pass? | [branching](docs/architecture/branching.md) |
| How do I scope and open the PR? | [PR discipline](docs/architecture/pr_discipline.md) |
| Why is it built this way? | [decision records](docs/architecture/decisions/README.md) |
| Is this handoff acceptable? | [acceptance checklist](docs/handoff_acceptance_checklist.md) |
| What has been measured, and what did it find? | [measurements index](docs/measurements_index.md) |

## The short version

1. Branch from a fresh `origin/develop` in a git worktree, not in the main checkout (see
   [the worktree rule](README.md#do-the-work-in-a-worktree-not-in-this-checkout)). `main`
   remains the release pointer. Follow the
   [current development workflow](docs/architecture/development_workflow.md) for the published
   baseline, temporary PR branches and archived work.
2. **One topic per PR.** A refactor never produces an artifact; a measurement never moves a
   file; a docs PR touches no source.
3. All five gates pass on your branch before review. CI runs the same five on Python 3.11 and
   3.13:

   ```bash
   .venv/Scripts/python -m ruff check .
   .venv/Scripts/python -m ruff format --check .
   .venv/Scripts/python -m mypy
   .venv/Scripts/lint-imports
   .venv/Scripts/python -m pytest -n auto --dist loadscope
   ```

   Run the full suite in parallel, the way CI does; the parallel full suite is the merge gate,
   and `-m "not slow"` is not a substitute for it. A change under `web/` also runs the checks in
   the [web guide](web/README.md).
4. `develop` merges through the GitHub merge queue. When the checks are green, the pull request
   is enqueued; the queue runs the required checks again on the grouped merge and makes the
   squash commit from the pull request's title and body. See
   [branching](docs/architecture/branching.md#protection).
5. Stay in your zone; shared boundaries need both owners (all three until 2026-09-25).
6. Live-path changes carry the replay check and respect the deadline freeze window.

## Where a new file goes

| New file | Goes in | Also update |
| --- | --- | --- |
| A Python module | The package of its ring in `src/squadopt/` ([architecture overview](ARCHITECTURE.md#2-rings)) | Nothing, if the import contracts pass |
| A Python package | `src/squadopt/<package>/` | The layers list and contracts in `pyproject.toml`, the ring table, `.github/CODEOWNERS` |
| A unit test | `tests/unit/test_<module>.py`, or `test_<module>_<topic>.py` | Nothing |
| An architecture rule as a test | `tests/architecture/` | The enforcement map in the architecture overview |
| An end-to-end or opt-in probe | `tests/integration/` | The [integration guide](tests/integration/README.md) for an opt-in probe |
| A repository command or runner | `scripts/` | One row in the [script catalogue](scripts/README.md) |
| A measurement record | Where its runner writes it under `docs/` | A row in the [measurements index](docs/measurements_index.md) |
| A pre-registration | `docs/research/<name>_prereg.md` | Frozen when it merges |
| A living document | The `docs/` folder of its audience ([documentation guide](docs/README.md)) | That folder's guide |
| A public schema | `docs/contracts/<contract>_v<N>.schema.json` | The code that validates it and, for `ui_view_v1`, `npm run gen:types` |
| A website module | The zone of `web/src/` it belongs to ([web guide](web/README.md)) | Nothing, if the web architecture tests pass |
| Operator configuration | `config/` ([configuration guide](config/README.md)) | The contract that reads it |
| Deployment configuration | `deploy/` ([deployment guide](deploy/README.md)) | The runbook that applies it |

## Setup

Python 3.11 or newer:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -e ".[api,dev]"
```

The test suite is entirely synthetic and offline: it needs neither the historical archive nor the
network.

## Commit messages

Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`, `test:`), imperative subject, and a
body that says what changed, what was measured, and **what deliberately did not change**.

Do not add AI attribution of any kind: no `Co-Authored-By` trailer, no assistant name in
commits, PR bodies, issues or files.
