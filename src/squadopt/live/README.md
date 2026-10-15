# `squadopt.live`

The domain records of the live season (R2, [ARCHITECTURE.md](../../../ARCHITECTURE.md)): the
decision for a real deadline, from the opening squad to a mid-season transfer plan; the season
ledger that freezes each decision; its settlement against what happened; and the season's rules
as a capture states them. `squadopt.application` composes these records into a member's advice,
the published trees and settlement, and `squadopt.platform` and the operational scripts import
some of them directly. Nothing here calls a live endpoint: the capture is taken by
`squadopt.platform.fpl_capture`, and every module reads bytes that were written down, which is
what lets a past decision be replayed exactly.

Its 23 Python files sit in one folder. This page places every one of them in exactly one
family.

Review: the owner ([ownership](../../../docs/architecture/ownership.md)). `ledger.py`, `tick.py`
and `recommendation.py` also list İbrahim in `.github/CODEOWNERS` as an alternative reviewer,
so either approval is enough for those three. Within 24 hours either side of a deadline only a
blocker fix merges here
([live-path freeze window](../../../docs/architecture/ownership.md#live-path-freeze-window)).

## The boundary

- **It imports inward only.** The layers list in `pyproject.toml` places it directly below the
  laboratory and above `planning`, so it may import `planning`, `scenarios`, `evaluation`,
  `optimization`, `prediction`, `features`, `data` and `contracts`, and today it imports each
  of them. It may not import `application`, `integration`, `platform` or `api`.
- **It imports no laboratory module.** The layers contract and "Product does not import the
  laboratory" both refuse it.
- **It reaches the solver through the decision core.** "The CP-SAT solver stays in the decision
  core" refuses `ortools` here; the transfer decision and the plan choice call `planning`,
  `optimization` and `scenarios`.
- **No outside world beyond files.** It imports no web framework, network client, model SDK or
  `sqlite3` ("Frameworks, network and databases stay in api and platform"), no repository
  script ("The package never imports the repository scripts"), and none of `subprocess`,
  `multiprocessing`, `concurrent`, `threading`, `signal`, `argparse` or `asyncio` ("Use cases
  and domain records import no process, thread, event-loop or command-line module").
- **Storage imports are held to today's.** "Use cases, domain records and features import no
  storage or source module" fails on any new import of the storage half of `squadopt.data`;
  today's are listed below.

Of third-party libraries it imports pandas, NumPy and SciPy.

## Deciding a deadline

| Module | What it does |
| --- | --- |
| `recommendation.py` | Turns a captured deadline snapshot into a squad recommendation, live for the next open deadline or as an exact replay of a stored one, from the operational control's projection; it also writes and reads the projection handoff (`projection_handoff_v1`) a mid-season decision uses. |
| `transfers.py` | The transfer decision for a mid-season deadline, from the squad, bank, free transfers, purchase prices and chips the ledger records: the transfer planner with a one-week horizon (`ledger_transfers_v1`). |
| `horizon.py` | Projects several gameweeks from one captured decision snapshot: one information state for the whole horizon, with only the calendar varying, as the builder `planning.horizon` asks for. |
| `report.py` | Assembles a recommendation and the provenance chain that lets it be rebuilt: the capture, its deadline, the model and the projection's fingerprint (`live_recommendation_v3`). |
| `risk.py` | Structured risk evidence for one already-optimized recommendation (`live_recommendation_risk_v1`), with an optional residual history read from a table and its manifest. |
| `plan_selection.py` | Chooses a window plan under a play mode by scoring a small menu of candidate plans on joint scenario paths (`mode_plan_selection_v1`). |
| `chip_strategy.py` | The chip rights a capture states, as the planner's chip availability for the opt-in chip strategy; it reads no live state. |

## The game's rules and money

| Module | What it does |
| --- | --- |
| `rules.py` | The season's rules as the source publishes them (scoring values, chips, transfer limits), read and validated from a capture's bootstrap payload without interpreting them (`season_rules_v1`). |
| `banking.py` | The free transfers a member holds at a deadline, modelled from the season history under the capture's rules. |
| `purchase_prices.py` | The price each held player was bought for, rebuilt by replaying the public transfers list over the opening picks. |
| `free_hit.py` | The two Free Hit rules more than one path obeys: no Free Hit in consecutive gameweeks, and which squad the next deadline restores. |
| `errors.py` | `LedgerError`, the error the live path's modules share, a kind of `DataError`. |

## The season record

| Module | What it does |
| --- | --- |
| `ledger.py` | The season ledger (`season_ledger_v1`): each gameweek's decision frozen at decision time, then its realized outcome, as immutable, checksummed entries landed from a staging folder under a per-gameweek lock. |
| `settlement.py` | Scores frozen decisions against what happened, without inventing missing decision-time information. |
| `tick.py` | One tick of the season loop (`season_tick_v1`): whether to capture, decide, settle or wait, from the clock, the held captures, the ledger and whether the gameweek's projection handoff exists; repeated calls give the same answer until something changes. |
| `calibration.py` | Compares the settled series with the development measurements: selection optimism, the captain's gap and player error (`live_calibration_v1`). It changes no projection; realized points are re-read from the settle capture each outcome names. |

## The football lane

The inputs and records of the experimental football model a member can choose in place of the
current model; see the [package map](../README.md#two-cross-cutting-names) for the lane as a
whole.

| Module | What it does |
| --- | --- |
| `football_artifact.py` | Reads a versioned, capture-bound football forecast; reading never fits or fetches a model. |
| `football_composite_basis.py` | Builds and verifies a required retained composite recipe, then reprojects news from its original weekly laws (`src/squadopt/live/football_composite_basis.py:697`, `src/squadopt/live/football_composite_basis.py:848`). |
| `football_composite_codec.py` | Reads canonical bounded source DTOs selected by code, rejecting duplicate fields and undeclared types (`src/squadopt/live/football_composite_codec.py:125`). |
| `football_horizon.py` | Opt-in football forecasts for a complete roster over a captured fixture calendar. |
| `football_observations.py` | Capture-bound availability information for the experimental window consumer, from explicit source percentages only; `transfers.py` uses it. |
| `minute_evidence.py` | Applies a source-verified exclusion of a full match to the football fixture components (`explicit_full_match_exclusion_v1`), keeping the probability of an appearance; it fits, fetches and publishes nothing. |

## Package surface

| Module | What it does |
| --- | --- |
| `__init__.py` | Re-exports the names of `calibration`, `horizon`, `ledger`, `plan_selection`, `recommendation`, `report`, `risk`, `rules`, `tick` and `transfers` that callers import from the package root. |

## Known violations here

ARCHITECTURE.md measures and schedules these; this list says where they are.

- **Storage imports.** 9 modules import the storage half of `squadopt.data` directly: 17
  edges from `banking`, `calibration`, `free_hit`, `horizon`, `ledger`, `purchase_prices`,
  `recommendation`, `rules` and `tick` to `data.snapshots`, `data.sources.fpl_live`,
  `data.sources.fpl_information`, `data.atomic` and `data._long_paths`. Each edge is an
  `ignore_imports` entry of "Use cases, domain records and features import no storage or source
  module" and may only go. The remedy is storage ports declared in `squadopt.application`, with
  file adapters in `platform` (Phase 3).
- **File access.** `ledger.py` writes, locks, lists and reads the ledger's entries;
  `recommendation.py` writes and reads projection handoffs; `calibration.py`,
  `football_artifact.py` and `risk.py` read files; and `tick.py` asks whether a handoff file
  exists. The remedy is the same storage ports (Phase 3). Until then
  `tests/architecture/test_use_case_file_io.py` allowlists these 6, and fails on any other
  module here that reads or writes a file.
