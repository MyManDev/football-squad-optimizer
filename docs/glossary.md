# Glossary

The terms this repository uses with a specific meaning, and the names it uses for more than one
thing. Where a term has a home in the code, the module is named; the code is the authority when
the two differ.

## Terms

| Term | Meaning | Where it lives |
| --- | --- | --- |
| Capture | Reading the Fantasy Premier League API at one instant and writing the bytes down unchanged; also the result, named like `fpl-live-20260821T143619Z-11bc603a8e1c`. Every later stage reads a capture, never the live API. | `squadopt.platform.fpl_capture` |
| Snapshot | The immutable, checksummed store of one capture on disk. It refuses to return bytes that no longer match what was recorded. | `squadopt.data.snapshots`, under `data/snapshots/` |
| Handoff | The in-season projection handoff: the projection table one model produced for the deadline a capture is open for. A mid-season decision refuses to run without it. | `squadopt.application.projection_handoff`, under `data/handoffs/` |
| Ledger | The season ledger: the immutable record of each gameweek's live decision and, later, its realized outcome. The committed summary is [the season ledger](season_ledger_2026-27.md). | `squadopt.live.ledger`, under `data/ledger/` |
| Tick | One step of the season loop: a pure decision about whether to capture, decide or settle now, given the clock and what is on disk. | `squadopt.live.tick`; `squadopt season tick` |
| Settle | Attaching the realized outcome of a gameweek to its decision once the gameweek is over, and publishing the settled view. | `squadopt.live.settlement`; the settled outcomes stage of the weekly run |
| Weekly run | The journaled run behind each publication. Its stages include the capture, the settled outcomes, the handoff, an optional decision for our own squad, every league, the site, the scoreboard and an optional publish. | `squadopt.platform.weekly_operations`; [weekly runbook](weekly_runbook.md) |
| League tree | The published documents of one league, under `data/leagues/<league_id>/` of the published site, listed by the site's league directory, `data/leagues.json` (committed under `web/public/`). | `squadopt.contracts.league_tree` |
| League list | The operator's list of the leagues the site serves (`league_list_v1`). | `config/leagues.json`, read by `squadopt.contracts.league_list` |
| Device plan | The inputs a member's one-week plan needs, published once per capture so the member's browser can solve the same problem the server solves. | `squadopt.application.device_plan`; [`league_device_plan_v1`](contracts/league_device_plan_v1.md) |
| Window | The number of gameweeks a plan covers: one, three or five. | `squadopt.application.advice_capabilities` |
| Chip forecast | The weekly chip rule applied to one member: whether to play a chip this gameweek. | `squadopt.application.chip_forecast`; [pre-registration](chip_forecast_prereg.md) |
| Manager's word | Model-coded club news applied as a declared constraint with a price, which the member switches on. | `squadopt.application.manager_words` |
| Football lane | The experimental football model a member can choose in place of the current model, and the `football_*` modules behind it. | [Experimental football model](live-football-model.md) |
| Phases A to H | The roadmap's stages: A measurement correctness, B deadline-safe evidence, C probabilistic player model, D Monte Carlo V2, E stochastic single-gameweek optimizer, F multi-gameweek rolling horizon, G design of experiments and Bayesian optimization, H advanced methods and product scaling. | [Roadmap](product/roadmap.md) |
| Record, evidence, operational state | The three tiers of ADR 0003. A record is committed under `docs/` with a row in the measurements index; evidence is the uncommitted expansion under `artifacts/`; operational state is the private data under `data/`. | [ADR 0003](architecture/decisions/0003-measurement-artifacts.md) |
| Pre-registration | A protocol committed before its measurement runs; frozen when it merges. File names end in `_prereg.md`. | `docs/` and `docs/research/` |
| Live path | `live`, `optimization`, `planning`, `prediction` and `scenarios`: the packages a live decision runs through. | [PR discipline](architecture/pr_discipline.md) |
| Freeze | No merge touching the live path within 24 hours either side of a deadline. | [Ownership](architecture/ownership.md) |
| Replay pin | A test that holds a recorded live decision to literal values: `test_the_recorded_gw1_replay_decision_holds` and `test_the_recorded_in_season_member_plan_holds`. | `tests/unit/test_live_recommendation.py`, `tests/unit/test_league_views.py` |
| `site-*` tag | The annotated tag of a production deploy of the website, `site-<season>-gw<NN>-<decision, settled or fixN>`. | [Branching](architecture/branching.md) |
| Ring | One of the five dependency rings R1 to R5, or the research side tree. | [Architecture overview](../ARCHITECTURE.md) |
| Laboratory | The research packages `experiments`, `backtest`, `bayesopt`, `recalibration` and `preflight`. No product package may import them. | [Dependency rules](architecture/dependency_rules.md) |

## One name, several things

| Name | Meanings |
| --- | --- |
| data | (1) `data/`, the private operational state at the repository root; (2) `squadopt.data`, the canonical data package; (3) `web/public/data`, the published views the website reads; (4) `web/src/data`, the website's data client and generated schema types. |
| fixtures | (1) test fixtures: `tests/fixtures/` and the `tests/football_*_fixtures.py` modules; (2) `web/src/fixtures/`, the website's test and development data; (3) football fixtures, the matches of a gameweek: `squadopt.data.fixtures`, `web/src/features/fixtures/` and the [fixture list](fixtures_view.md). |
| contracts | (1) `squadopt.contracts`, the vocabulary package; (2) `docs/contracts/`, the versioned public schemas the code and the website validate against. |
| preflight | (1) `squadopt.preflight`, the laboratory's validator for residual exports and measurement records; (2) the first stage of the weekly run, which checks the checkout and the inputs before anything is spent. |
| scripts | (1) `scripts/`, the repository's commands and measurement runners; (2) `web/scripts/`, the website's build and deployment checks; (3) `workers/fpl-probe/scripts/`, the probe's deployment steps. |
