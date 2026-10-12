# The `squadopt` package

`squadopt` is the one import package of the installed distribution
([ADR 0001](../../docs/architecture/decisions/0001-modular-monolith.md)). This page maps its
packages: the ring each one sits in, where the layer order places it, who reviews it, which
import contracts check it, and the module families inside it. The rings, the deployment units
and the reasons behind them are in [ARCHITECTURE.md](../../ARCHITECTURE.md);
[the dependency rules](../../docs/architecture/dependency_rules.md) say how code moves between
packages.

## Packages

**Layer** is the package's position in the layers list of `pyproject.toml`, counted from the
top: that contract lets a package import the packages below it and none above it, and the other
contracts narrow what it may import further. **Checked by** names the
import contracts that hold the package as a source, by the keys in the next table. **Owner**
is the review authority of `.github/CODEOWNERS` and
[ownership](../../docs/architecture/ownership.md): "the owner" is `@ErtugrulS32175`,
"İbrahim" is `@SpeedyV5`, "both" is a shared boundary that needs each of them, and "either"
lists both as alternative reviewers. **Known violation** names the entry of
[ARCHITECTURE.md, known violations](../../ARCHITECTURE.md#7-known-violations) that applies;
the measurements and remedies are there.
`tests/architecture/test_architecture_rings.py` holds the ring, layer and checked-by columns
to `pyproject.toml`.

| Package | Ring | Layer | Owner | Checked by | Known violation |
| --- | --- | --- | --- | --- | --- |
| `api` | R4, R5 | 1 | either | C1, C2, C3, C5, C8 | none |
| `platform` | R4, R5 | 2 | either; the `club_news_*` modules are İbrahim's zone | C1, C2, C5, C8 | declares 15 of the package's 24 typed ports; mixes deployment roles; 6 modules name `docs/contracts` by a relative path |
| `application` | R3 | 3 | the owner | C1, C2, C4, C5, C8, C9 | imports the storage half of `data`; holds six laboratory modules; 2 modules name `docs/contracts` by a relative path; declares 3 ports |
| `experiments` | Research | 4 | the owner | C1, C4, C5, C8 | none |
| `backtest` | Research | 5 | both | C1, C4, C5 | none |
| `recalibration` | Research | 6 | the owner | C1, C4, C5, C8 | none |
| `preflight` | Research | 7 | the owner | C1, C4, C5, C8 | none |
| `bayesopt` | Research | 8 | the owner | C1, C4, C5, C8 | none |
| `live` | R2 | 9 | the owner; `ledger.py`, `tick.py` and `recommendation.py` either | C1, C2, C4, C5, C8, C9 | imports the storage half of `data` |
| `planning` | R2 | 10 | the owner | C1, C2, C4, C5, C6, C7 | imports private names of `optimization.optimizer` |
| `scenarios` | R2 | 11 | the owner | C1, C2, C4, C5, C6, C7 | imports private names of `optimization.optimizer` |
| `evaluation` | R2 | 12 | the owner | C1, C2, C4, C5, C6, C7 | none |
| `integration` | R3 | 13 | the owner | C1, C2, C4, C5, C8 | a use-case module placed as its own layer |
| `optimization` | R2 | 14 | the owner; `config.py` both | C1, C2, C4, C5, C6, C7 | the CP-SAT driver has no public port |
| `prediction` | R2 | 15 | İbrahim | C1, C2, C4, C5, C7, C8 | none |
| `features` | R2 | 16 | İbrahim | C1, C2, C4, C5, C8 | imports the storage half of `data` |
| `data` | R1, R4 | 17 | İbrahim; `schema.py` both | C1, C2, C4, C5, C8 | one package in two rings, at the bottom of the layer order |
| `contracts` | R1 | 18 | both | C1, C2, C4, C5, C6, C7, C8 | reads and writes files (`league_list.py`, `league_tree.py`) |

The import contracts, in the order `pyproject.toml` declares them:

| Key | Contract |
| --- | --- |
| C1 | Layered architecture |
| C2 | Product does not import the laboratory |
| C3 | HTTP adapter uses only public boundaries |
| C4 | Frameworks, network and databases stay in api and platform |
| C5 | The package never imports the repository scripts |
| C6 | The decision core imports no OS or process module |
| C7 | The decision core and prediction import no storage or source module |
| C8 | The CP-SAT solver stays in the decision core |
| C9 | Use cases and domain records start no processes or threads |

The research packages are also the forbidden side of C2: no product package may import them,
so the research arm is checked from both sides.

## Module families

A family is a set of modules that share a name prefix or a job. `platform`, `application` and
`experiments` have their own guides, which place every module.

| Package | Families |
| --- | --- |
| `api` | `app` (the FastAPI routes), `runtime` (`build_app`, the API process's composition), `views` (published-view reads), `contributions` (community observations) |
| `platform` | Weekly run, advice API services, advice queue and workers, captures, club news and the model adapter, run records and recovery, the installed CLI: [platform guide](platform/README.md) |
| `application` | Member advice, chips and strategies, the device plan, weekly and multi-week planning, league and site publication, the season ledger and settlement, evidence exports, the football lane: [application guide](application/README.md) |
| `experiments` | The screening design and its runner, the season chain, Phase C to E readings, Benchmark V2, the football studies, chip timing: [experiments guide](experiments/README.md) |
| `backtest` | Walk-forward `folds` and `splits`; the production benchmark (`production`, `production_benchmark`, `production_reporting`); the learned candidate (`learned`, `learned_candidate`); `candidate_residuals`, `horizon_decay`, `opening_prior` |
| `recalibration` | `study`, `measurement`, `models`, `reporting` |
| `preflight` | `validator` (residual-export handoffs), `measurement` (committed records), `models`, `reporting` |
| `bayesopt` | `optimizer`, `evaluation`, `models`, and `football_search` for the football component study |
| `live` | The season ledger and the decision loop (`ledger`, `tick`, `recommendation`, `transfers`, `settlement`, `report`, `horizon`, `calibration`); the game's rules and money (`rules`, `errors`, `banking`, `purchase_prices`, `free_hit`); plan choice (`plan_selection`, `chip_strategy`, `risk`); the football lane's inputs and records (`football_artifact`, `football_horizon`, `football_observations`, `minute_evidence`) |
| `planning` | The CP-SAT horizon planner (`optimizer`, `horizon`, `models`); lookahead and repair (`lookahead`, `guarded`, `segmented`, `refinement`, `recourse`, `recourse_chips`, `observed`); chips (`chip_strategy`, `chip_tail`); expected values and pricing (`expected_swap`, `expected_window`, `lineup_utility`, `pricing`, `acquisition`); policy comparison (`policy_comparison`, `policy_seed`); `football_exact_lineup` |
| `scenarios` | Scenario generation and paths (`generator`, `paths`, `models`, `components`, `decomposition`); scoring and selection (`evaluation`, `decision_scoring`, `selection`, `expected_lineup`, `transfer_decisions`); rivals and rank (`rivals`, `rank`, `optimization`); `reporting`; the football lane (`football`, `football_diagnostics`, `football_lineups`) |
| `evaluation` | Fold scoring and inference (`evaluator`, `scoring`, `statistics`, `promotion`, `benchmarks`, `models`, `cohorts`); component evaluation (`component_decisions`, `component_handoff`, `component_metrics`); audits and gates (`appearance`, `appearance_recalibration`, `live_projection_audit`, `live_series`, `participation_composition`, `prediction_gate`, `prior_minutes_level`, `projection_level`, `rotation_ceiling`, `top100_effect`) |
| `integration` | One module, `integration.py`: optimizes a squad from a canonical projection CSV |
| `optimization` | The CP-SAT driver (`optimizer`); configuration, validation and results (`config`, `validation`, `models`); objective coefficients and top-K candidates (`coefficients`, `candidates`); the squad constraints shared with every CP-SAT consumer (`decisions`) |
| `prediction` | The control and production projection (`baseline`, `production`, `projection`, `config`, `factors`, `integration`, `availability`, `minutes`, `opening`, `in_season`, `participation`, `participation_updates`, `elite_evidence`); the component model (`components`, `component_dataset`, `component_models`, `defcon_component`); the learned candidate (`learned`, `learned_rate`); the football lane (15 `football*` modules) |
| `features` | Feature building (`builder`, `rolling`, `strength`, `fixtures`, `cross_season`, `config`); evidence tables (`evidence`, `evidence_artifact`, `rotation_evidence`, `rotation_evidence_artifact`, `settled_outcomes`, `component_targets`); the football lane's inputs (8 `football_*` modules) |
| `data` | Vocabulary (`schema`, `errors`, `timestamps`, `identity`, `claim_identity`, `validation`, `cleaning`, `cohorts`, `fixtures`); storage (`snapshots`, `loaders`, `atomic`, `adapters`, `checksums`, `tables`, `pipeline`, `source_revision`, `_long_paths`); `sources/`: the FPL API (`fpl_live`, `fpl_information`, `fpl_set_pieces`), the historical archive (`vaastav`, `football_history`), club news (8 `club_news*` modules) and the official injury list (`premier_league_injuries`) |
| `contracts` | Shared vocabulary (`players`, `factors`, `preferences`, `information`, `injuries`, `run_logs`); league identity (`league`, `league_list`, `league_tree`, `league_publication_identity`); football point accounting and explanations (`football_point_accounting`, `football_explanations`); `honesty_stems`, generated by `scripts/generate_honesty_stems.py` |

## Two cross-cutting names

**The football lane.** Modules whose names start with `football` form the experimental football
model a member can choose in place of the current model (`PREDICTION_MODELS` in
`application/advice_capabilities.py`), and the inputs, plans and records behind it. It is a
lane, not a package: each module sits in the package whose ring matches its job, from
`features` and `prediction` up to `application` and `platform`, and the research studies of
it sit in `experiments` and `bayesopt`. Six `application` modules of the lane end in
`_experiment` and are laboratory code in a product package; ARCHITECTURE.md lists them as a
known violation, and the run-boundary probe reports one if a product entry point loads it.

**`integration.py`.** The only module directly under `squadopt` besides `__init__.py`. It reads a canonical
projection CSV and optimizes a squad from it, so its job is a use case (R3), but the layer
order gives it a layer of its own between `evaluation` and `optimization`, because it imports
only `data` and `optimization`. The package root re-exports `optimize_squad_from_csv`, with
the public names of `optimization` and `evaluation`, lazily (`__getattr__` in `__init__.py`),
so `import squadopt` loads neither the module nor the solver.
