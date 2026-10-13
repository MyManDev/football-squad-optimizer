# Tests

The Python test suite is entirely synthetic and offline: it needs neither the historical
archive nor the network. The website's tests live beside their code under `web/`
([web guide](../web/README.md)).

## Layout

| Path | Holds |
| --- | --- |
| `unit/` | Tests of one module or one behaviour, in a flat folder; `unit/conftest.py` holds shared setup for the member-menu HTTP and publication checks |
| `architecture/` | The architecture fitness functions: the rings and the documents that state them, imports of the `data` package root, the shrink-only ratchets on storage imports, on file access in `contracts`, the decision core and `prediction` and in `application`, `live` and `features`, and on paths into `docs/contracts` outside their one resolver, import boundaries at run time, the operator entry points of `platform`, the storage adapters against their ports, the script catalogue and the package guides, documentation paths, links, reachability and the root of `docs/`, the measurements index, record provenance, the type-checked file set, dependency pins, the operations documents and the roadmap ([architecture overview](../ARCHITECTURE.md#6-enforcement-map)) |
| [`integration/`](integration/README.md) | End-to-end chains across packages and processes, including the opt-in acceptance probes |
| `fixtures/` | Shared synthetic data and helpers, imported as `tests.fixtures`, including the synthetic bases and numerical oracles of the football experiment tests (`football_*_fixtures.py`) |
| `conftest.py` | Shared pytest fixtures, and the hook that marks every test under `integration/` |

## Running the suite

The merge gate is the full suite, run in parallel the way CI runs it:

```console
python -m pytest -n auto --dist loadscope
```

`testpaths` in `pyproject.toml` is `tests`, so the command collects all three folders.

## Naming

- A test file is named after the module it tests, `test_<module>.py`, with a topic suffix when
  one module needs more than one file, `test_<module>_<topic>.py` (for example
  `unit/test_advice_worker.py` and `unit/test_advice_worker_timestamps.py`).
- A fitness function in `architecture/` is named after the rule it holds, for example
  `test_operations_docs_match_the_workflows.py`.
- A test function says what holds, in words: `test_the_recorded_gw1_replay_decision_holds`.
- A file name must be unique across `unit/`, `integration/` and `architecture/`; the next
  section says why.

## Why `unit/` has no `__init__.py`

`tests/` is a package, but `unit/`, `integration/` and `architecture/` are not. Under pytest's
default import mode, a test file in a folder without `__init__.py` is imported under its bare
file name, so two test files with the same name in two of these folders would collide. Adding
`tests/unit/__init__.py` would change how ruff sorts imports and how pytest imports every
test there; [the data follow-ups](../docs/data_followups.md) record that it was left to the
software owner, and `tests/architecture/test_documentation_paths.py` lists it as a proposed,
deliberately absent file.

## Markers

`pyproject.toml` declares two markers, and `--strict-markers` refuses any other:

| Marker | Applied | Meaning |
| --- | --- | --- |
| `integration` | Automatically, by `conftest.py`, to every test under `integration/` | An end-to-end test |
| `slow` | By hand | A solver-heavy test of more than about five seconds. `-m "not slow"` is not a substitute for the full suite |

## Replay pins

Two tests pin a recorded live decision to literal values. If either one moves, either the
change altered a live decision, which the pull request says explicitly, with the live-path
owner's agreement and the literals updated in the same commit, or it is a bug
([PR discipline](../docs/architecture/pr_discipline.md#the-live-path)):

| Test | File | Pins |
| --- | --- | --- |
| `test_the_recorded_gw1_replay_decision_holds` | `unit/test_live_recommendation.py` | The opening-gameweek decision |
| `test_the_recorded_in_season_member_plan_holds` | `unit/test_league_views.py` | An in-season member plan and the byte hash of its published advice |

## Opt-in probes

Four tests under `integration/` skip unless an environment variable switches them on, because
they need a browser, a container image, Node or the local machine's resources. The
[integration guide](integration/README.md) lists them with their variables and the CI jobs that
run them.
