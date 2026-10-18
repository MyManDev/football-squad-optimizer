# `squadopt.experiments`

The largest package of the research arm, beside `backtest`, `bayesopt`, `recalibration` and
`preflight` ([ARCHITECTURE.md](../../../ARCHITECTURE.md), "The research arm and the three
tiers"). It holds the measurement studies: experiment designs, readings and reports whose
results are committed as records under `docs/`. Installing the package activates none of it;
the [roadmap](../../../docs/product/roadmap.md) says which models and policies members receive.

Review: the owner ([ownership](../../../docs/architecture/ownership.md)).

## The boundary

- **No product package imports it.** The contract "Product does not import the laboratory" in
  `pyproject.toml` lists every package outside the research arm as a source and this package as
  forbidden, with `allow_indirect_imports = false`, so a product module may not reach it
  through another module either.
- **It imports downward only.** The layers list places it above `live` and below
  `application`, so it may import the other four research packages, the domain packages,
  `data` and `contracts`, and it may not import `application`, `platform` or `api`. It is also a source of the contracts that keep web
  frameworks and network clients out, keep the repository scripts out, and keep `ortools` in
  the decision core: it reaches the solver only through the decision core's packages.
- **No operational command loads it.** `tests/architecture/test_run_boundary.py` imports every
  operational row of the [script catalogue](../../../scripts/README.md) in one interpreter,
  apart from the three laboratory tools it names, and fails if a laboratory module is loaded. `scripts/_experiment_cli.py` imports this
  package, so an operational command takes its provenance helpers from
  `scripts/_provenance.py` instead.

## How a runner uses it

A measurement runner in `scripts/` parses its arguments, reads its inputs, calls a function
here and writes the result. Most runners take their provenance and writers from
`scripts/_experiment_cli.py`: `write_json`, `write_text` and the git revision the record
names. The catalogue's [measurement runners](../../../scripts/README.md#measurement-runners)
table names the record each runner writes.

## Where the results go

[ADR 0003](../../../docs/architecture/decisions/0003-measurement-artifacts.md) sorts what a
study produces into three tiers:

- **Records** are committed under `docs/`, usually a JSON file beside its Markdown twin, with a
  row in the [measurements index](../../../docs/measurements_index.md). Research programme
  records live under `docs/research/`. A record names the commit that produced it, with a list
  of exceptions that may only shrink (`tests/architecture/test_records_name_their_code.py`).
  A record stays at its path: moving one is a code change under ADR 0003, rule 5.
- **Evidence**, the per-fold or per-scenario expansion behind a record, goes to the git-ignored
  `artifacts/` folder or to an output directory the operator names.
- **Operational state** under `data/` is the third tier; it is backed up, not committed.

A pre-registered study's protocol is a `*_prereg.md` file, frozen when it merges; some research
programmes under `docs/research/` name theirs `*_protocol.md`.

## The package root is an interface

`__init__.py` re-exports a fixed set of names, listed in `__all__`, and runners and tests import
them from the package root. Five of them (`PromotionPolicy`, `ExperimentError`,
`ExperimentConfigurationError`, `ExperimentExecutionError` and
`season_aware_moving_block_interval`) are defined in `squadopt.evaluation`, and
`tests/architecture/test_layer_contracts.py` holds three of those to the objects defined there.
Add a name when a runner needs it from the root; remove or repoint one only together with every
module that imports it.

## Module families

| Family | Modules |
| --- | --- |
| The screening design, the frozen holdout and shared reporting | `config`, `design`, `models`, `runner`, `reporting`, `statistics` |
| Season chains and planning studies | `season_chain`, `season_chain_runs`, `multi_gw_rehearsal`, `terminal_value`, `policy_objective`, `planning_shortlist`, `chip_threshold`, `calendar_chip` |
| Model, residual and rating studies | `control_residuals`, `residual_signal_scan`, `opening_prior_exposure`, `opponent_projection`, `team_rating`, `team_rating_cs`, `positional_defence`, `preseason_difficulty`, `published_difficulty_live`, `continuation_diagnostic` |
| Phase C to E readings and the shadow report | `phase_c_ablation`, `phase_c_reporting`, `component_squad_calibration`, `phase_e_shadow`, `shadow_report` |
| Benchmark V2 | `benchmark_v2`, `benchmark_v2_live` |
| Football studies | `football_components`, `football_defcon`, `football_minutes`, `football_share_sizing`, `football_windows` |
| Private football model experiments | `football_flag_experiment`, `football_load_experiment`, `football_phase_experiment`, `football_score_state_experiment`, `football_tactical_experiment`, `football_unit_experiment` |
| Single gate readings | `defcon_component_reading`, `rank_tail_selector`, `rank_conditional_shrinkage` |
| The package root, an interface (see above) | `__init__` |

Each study module's docstring states its study; the runner that calls it is in the
[script catalogue](../../../scripts/README.md). The six private football model experiments
have no runner: only tests import them, and the tests of five of them take their synthetic
bases from the `football_*_fixtures.py` modules in `tests/fixtures/`. They lived in
`squadopt.application` until Phase 2 of
[ADR 0010](../../../docs/architecture/decisions/0010-clean-architecture-rings-and-repository-layout.md)
moved them here with no re-export.
