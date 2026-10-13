# `squadopt.application`

The use-case ring (R3, [ARCHITECTURE.md](../../../ARCHITECTURE.md)): transport-neutral
operations that compose the domain packages into a member's advice, the published league and
site trees, settlement, the scoreboard and the chip and strategy menus. Entry points in
`squadopt.platform`, `squadopt.api` and `scripts/` call these services; they do not reimplement
them. The package imports no platform, API or script code, no web framework or network client,
and no process, thread, event-loop or command-line module (the contracts "Layered
architecture", "Frameworks, network and databases stay in api and platform" and "Use cases and
domain records import no process, thread, event-loop or command-line module" in
`pyproject.toml`). One module still starts a process indirectly: `advice_record.py` calls
`source_revision()` in `squadopt.data.source_revision`, which runs `git`; ARCHITECTURE.md lists
it as a known violation.

Its 62 Python files, 57 at the top level, four in the `strategies/` subpackage and the package
file of `ports/`, are placed by this page: every one of them is in exactly one family. Review:
the owner ([ownership](../../../docs/architecture/ownership.md)).

## Member advice

One member's plan, the menu a request may ask for, and the record of what the member was told.

| Module | What it does |
| --- | --- |
| `advice.py` | One member's advice as a pure application call, `advise_entry`. |
| `advice_capabilities.py` | The computable member requests, shared by the producer and the transport adapters. |
| `advice_menu.py` | One entry point for the whole member menu, for a caller that answers one request. |
| `advice_variants.py` | The menu beyond the one-week plan: windows and rival strategies, each with the Top 100 influence. |
| `advice_record.py` | The immutable record of what one member was told, for one gameweek. |
| `entries.py` | The seam for advice by FPL entry id: the shapes of a team's picks and of the advice for it. |
| `capture_entries.py` | Reads member picks from one captured response, by canonical player code. |
| `lineup_publication.py` | Serializes a solved lineup with the deterministic completion rule. |
| `mode_selection.py` | Per-mode plan choice for one league member, priced on shared scenario paths. |
| `phase_e.py` | Reviewed calibration identities and internal member-transfer diagnostics. |

## Chips, strategies and member weights

The switches a member turns on: a chip, a rival strategy, the Top 100 weight, the manager's
word.

| Module | What it does |
| --- | --- |
| `advice_chips.py` | A chip the member chose to play, on the one-week pure-points plan. |
| `advice_chip_strategy.py` | Joint chip and transfer advice, separate from the one-week chip switch. |
| `chip_forecast.py` | The chip forecast: the weekly chip rule applied to one member, as a pure function (`chip_forecast_v1`). |
| `chip_forecast_publication.py` | Binds the forecast to one member and the capture the product reads. |
| `strategies/__init__.py` | The catalogue's package surface: declared constraints, expected-points pricing, a closed envelope. |
| `strategies/catalog.py` | The catalogue: declared structural constraints, priced in expected points. |
| `strategies/candidates.py` | Solves one strategy's plan: the declared constraint, priced against the control. |
| `strategies/rule.py` | Which of the computable strategies a member plays this week. |
| `top100_weight.py` | The Top 100 influence: a member's own weight on last week's Top 100 starting elevens. |
| `manager_words.py` | The manager's word, as a constraint the member switches on. |

## Device plan

| Module | What it does |
| --- | --- |
| `device_plan.py` | What a member's one-week plan needs, published so the member's own browser can solve it ([`league_device_plan_v1`](../../../docs/contracts/league_device_plan_v1.md)). |

## Weekly and multi-week planning

| Module | What it does |
| --- | --- |
| `weekly_plan.py` | Transport-neutral weekly planning, provenance and the run's preflight rules. |
| `horizon_plans.py` | The application command for deterministic transfer horizons. |
| `horizon_batch.py` | Runs the one-, three- and five-week planning evidence together. |
| `horizon_publish.py` | Validates planning evidence before it is attached to a public ledger view. |
| `planner_review.py` | Offline decision review with explicit information provenance and member-owned weights. |

## Squad optimization from a projection CSV

| Module | What it does |
| --- | --- |
| `projection_csv.py` | Reads a canonical projection CSV and optimizes one squad from it (`optimize_squad_from_csv`). The package root re-exports it lazily, and `squadopt.integration` re-exports it until the release after the next `site-*` tag. |

## League and site publication

The static JSON trees the website reads: the per-member league trees and the season site.

| Module | What it does |
| --- | --- |
| `league_publication.py` | Assembles a member publication from an explicit capture. |
| `league_views.py` | Renders the per-member league views: the JSON tree the league pages read. |
| `league.py` | The league view: our season against everyone else playing the same game. |
| `league_tree_identity.py` | Records the complete protected league set after a normal writer finishes. |
| `publication_history.py` | Explicit historical inputs for prospective current-season publication. |
| `site_publication.py` | Assembles the static site from ledger state and an optional pinned capture. |
| `site.py` | Writes the static JSON tree a frontend renders. |
| `build.py` | Builds `ui_view_v1` view models from the live path's records. |
| `views.py` | The view models of the `ui_view_v1` contract. |
| `contract.py` | The `ui_view_v1` contract: what the static JSON tree promises a frontend. |
| `fixtures_view.py` | The season's schedule and results as one capture stated them (`fixtures_v1`). |
| `player_catalog.py` | The complete FPL roster for browsing, independent of the optimizer's pool. |

## Season ledger, settlement and scoreboard

| Module | What it does |
| --- | --- |
| `commands.py` | Transport-neutral commands for the live season ledger: decide, roll and settle. |
| `season.py` | The public service for one scheduled season tick. |
| `settled_outcomes.py` | Accumulates what happened, one artifact per settled gameweek. |
| `settled_publication.py` | Publishes completed outcomes without producing another decision. |
| `scoreboard.py` | The weekly scoreboard: our paper squad beside the league, the Top 100 and the field. |
| `scoreboard_baselines.py` | Reconstructs labelled human baselines from decision-time information only. |
| `live_score.py` | A replaceable live score view, never an immutable ledger outcome (`live_score_v1`). |
| `live_price_honesty.py` | Stated price against realized cost, from recorded advice; solves nothing. |
| `weekly_suggestion_eval.py` | Read-only, settled evaluation of recorded member advice; never invokes a solver. |

## Evidence exports and handoffs

| Module | What it does |
| --- | --- |
| `projection_handoff.py` | Produces the in-season projection handoff a mid-season decision needs. |
| `player_evidence.py` | Exports one `player_evidence_v1` table as the identity-free CSV and manifest Phase C reads. |
| `rotation_export.py` | The installed, transport-neutral rotation evidence export. |
| `evidence_io.py` | Stable UTF-8 serialization shared by the evidence producers. |
| `defcon_component.py` | An offline adapter for the fixed, unpromoted 2026-27 DEFCON augmentation. |

## The football lane

The experimental football model a member can choose in place of the current model
(`PREDICTION_MODELS` in `advice_capabilities.py`). These modules are product code and are
opt-in. The lane's private model experiments, the `football_*_experiment` modules, are
laboratory code and live in [`squadopt.experiments`](../experiments/README.md); no module here
may end in `_experiment` (`tests/architecture/test_run_boundary.py`).

| Module | What it does |
| --- | --- |
| `football_live.py` | Produces the optional live football forecast from an immutable capture and archive. |
| `football_context.py` | Binds captured feed availability and source-resolved manager claims to the football input. |
| `football_participation.py` | Binds captured participation evidence to the experimental football window. |
| `football_roles.py` | Internal fixture-role estimates and their restricted public explanation. |
| `football_information.py` | The public conditional plan explanation, with base points apart from choice utility. |
| `football_candidate.py` | The read-only football candidate handoff: forecasts, plans, shared worlds and rival utility. |
| `football_window_review.py` | Shared match-world evaluation across complete three- and five-week candidate plans. |

## Storage ports

The home [ADR 0011](../../../docs/architecture/decisions/0011-storage-ports-and-platform-split.md)
(decision 1) gives the storage ports only the use cases consume: one module per port group and
no barrel, so the pull requests that land different groups never edit the same file. The
package is a source of the contract "The decision core imports no storage or source module",
so it imports nothing from the storage half of `data`; its file adapters are the singletons of
`squadopt.platform.storage`, and `tests/architecture/test_storage_ports.py` holds each adapter
to its port. It holds no port yet: each group lands in its own pull request.

| Module | What it does |
| --- | --- |
| `ports/__init__.py` | The package file, a docstring that names the port groups: `archive`, `publication`, `artifacts`, `club_news`, `rotation_evidence`, `advice_records` and `revision`. |

## Package surface

| Module | What it does |
| --- | --- |
| `__init__.py` | Re-exports the public operations and read models: the ledger commands, the season tick, the horizon commands, the league view, the site builder, the view builders and models, and the `ui_view_v1` contract. |

## Known violations here

ARCHITECTURE.md measures and schedules these; this list says where they are.

- **Storage imports.** Modules here import the storage half of `squadopt.data` (captures,
  atomic writes, loaders) directly. The remedy is storage ports declared in `ports/`, with
  file adapters in `squadopt.platform.storage` (ADR 0011, decision 1; both homes exist and
  hold no module yet). Until then the contract "Use cases, domain records and features
  import no storage or source module" holds them to today's imports: 89 edges from 30 modules,
  each an `ignore_imports` entry that may only go.
- **File access.** 24 modules here read or write files themselves, among them
  `league_publication.py`, `league_views.py` and `site.py` (the published trees),
  `advice_record.py`, and `player_evidence.py` and `rotation_export.py` (the evidence exports).
  The remedy is the same storage ports (Phase 3). Until then
  `tests/architecture/test_use_case_file_io.py` allowlists the 24, and fails on any other
  module here that reads or writes a file.
- **Ports.** Three typed ports are declared here: `DecisionVerifier` in `commands.py`,
  `EntryPicksProvider` in `entries.py` and `TickObserver` in `season.py`.
- **Paths to `docs/contracts`.** `contract.py` names `docs/contracts/ui_view_v1.schema.json`
  as the default target of `write_ui_view_schema`, and `chip_forecast.py` names
  `docs/contracts/chip_forecast_v1.schema.json` as a constant the tests read. Neither reads the
  file when it runs. `tests/architecture/test_runtime_contract_paths.py` allowlists both, with
  the six in `platform`, and fails on any other module that names the folder.
