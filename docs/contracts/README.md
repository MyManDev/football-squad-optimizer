# Contracts

The versioned shapes that cross a boundary: the documents the weekly run publishes for the
website, the advice API's requests, answers and jobs, the run records of the installed CLI, and
the notes that define a contract in prose. A contract's version is part of its name
(`ui_view_v1`) and of every document that carries it (`contract_version`).

## Rules

- **A version changes only when the meaning changes**, in a pull request that says so; renaming
  a field or changing what a value means is a version change even when it looks cosmetic
  ([ADR 0002](../architecture/decisions/0002-contract-versioning.md), decision 5). A shared
  version identity is declared once, in `squadopt.contracts` or in the module that owns the
  contract.
- **A generated schema is changed in code, not here.** Twelve of the schemas below are written
  by a Python function, and a unit test requires the committed file to equal that function's
  output, so an edit made only to the file fails the test. Change the function, then regenerate
  the file from it.
- **Nothing here moves.** Tests read these files by path, `npm run gen:types` in `web/` reads
  `ui_view_v1.schema.json` by path, the schema writers default to these paths, the website's
  test support imports `honesty_words.json` directly, and the backend restart
  (`scripts/release/restart_backend.ps1`) refuses, unless `-Force`, when `docs/contracts`
  differs from the live `site-*` release.

No module of the package reads a schema from this folder when it runs. The validators the API
runs are built from the same Python functions. The published site carries its own copies of
the `ui_view_v1`, `live_score_v1` and `fixtures_v1` schemas under `data/schema/`, which
`src/squadopt/application/site.py` writes from those functions, and the settled publication
checks a candidate against the copies the accepted site carries.

## Generated schemas

| File | Written by | Read by | Test that holds the file to the code |
| --- | --- | --- | --- |
| `advice_read_v1.schema.json` | `advice_read_schema()` in `src/squadopt/platform/advice_documents.py` | The advice validator in the same module; the website's runtime counterpart, `web/src/features/league/advice/adviceShape.ts` | `tests/unit/test_api_advice_routes.py` |
| `artifact_record_v1.schema.json` | `artifact_record_schema()` in `src/squadopt/platform/artifacts.py` | The artifact registry of the installed CLI | `tests/unit/test_platform_artifact_registry.py` |
| `backend_api_v1.schema.json` | `backend_api_schema()` in `src/squadopt/platform/api_contract.py` | The HTTP API's request and response documents | `tests/unit/test_backend_api_contract.py` |
| `backend_jobs_v1.schema.json` | `backend_jobs_schema()` in `src/squadopt/platform/jobs_contract.py` | The advice queue's job records | `tests/unit/test_jobs_contract.py` |
| `chip_forecast_v1.schema.json` | `chip_forecast_schema()` in `src/squadopt/application/chip_forecast.py` | A member's chip forecast in the league views; the browser's restatement of the rule, `web/src/features/league/device/chipForecast/rule.ts`, tested against `web/src/fixtures/chip-forecast/cases.json`, which `scripts/export_chip_forecast_fixture.py` generates | `tests/unit/test_chip_forecast.py` |
| `fixtures_v1.schema.json` | `fixtures_schema()` in `src/squadopt/application/fixtures_view.py` | The fixture list page, `web/src/features/fixtures/types.ts` | `tests/unit/test_application_fixtures_view.py` |
| `league_capabilities_v1.schema.json` | `league_capabilities_schema()` in `src/squadopt/platform/advice_documents.py` | The capabilities validator in the same module; `web/src/features/league/advice/adviceCapabilities.test.ts` | `tests/unit/test_api_advice_switches.py` |
| `league_state_v1.schema.json` | `league_state_schema()` in `src/squadopt/platform/advice_documents.py` | The league state validator in the same module | `tests/unit/test_api_advice_routes.py` |
| `live_score_v1.schema.json` | `live_score_schema()` in `src/squadopt/application/live_score.py` | The live score view, `web/src/data/liveScore.ts` | `tests/unit/test_application_live_score.py` |
| `run_manifest_v1.schema.json` | `run_manifest_schema()` in `src/squadopt/platform/manifest.py` | The run manifests of the installed CLI | `tests/unit/test_platform_run_context.py` |
| `ui_view_v1.schema.json` | `ui_view_schema()` in `src/squadopt/application/contract.py` | The season site's views; `npm run gen:types` generates `web/src/data/schema.ts` from it | `tests/unit/test_application_views.py` |
| `weekly_suggestion_history_v1.schema.json` | `history_schema()` in `src/squadopt/platform/history_documents.py` | The recorded weekly history that `src/squadopt/application/weekly_suggestion_eval.py` produces | `tests/unit/test_recorded_plan_history.py` |

## Hand-written schemas and contract notes

These are written by hand, and the tests beside each one hold its producer or its examples to
it.

| File | Contract | Producer or subject | Tests |
| --- | --- | --- | --- |
| [member_baseline_record_v1.md](member_baseline_record_v1.md) | One independent server baseline per entry and capture, shared by tracked leagues | `src/squadopt/application/advice_record.py`, `src/squadopt/application/league_publication.py` | `tests/unit/test_tracked_baselines.py`, `tests/unit/test_advice_record.py` |
| `league_member_movement_v1.schema.json` | A member's captured rank movement in the league views | `src/squadopt/application/league_views.py` | `tests/unit/test_league_views.py` |
| `member_week_horizon_v1.md`, `member_week_horizon_v1.schema.json` | The optional `series-horizon.json` beside a league's scoreboard | `src/squadopt/application/weekly_suggestion_eval.py`; read by `web/src/features/league/history/liveSeries.ts` | `tests/unit/test_member_week_horizon_contract.py`, `tests/unit/test_weekly_suggestion_eval.py` |
| `scoreboard_comparisons_v1.md`, `scoreboard_comparisons_v1.schema.json` | The `comparisons` extension of each scoreboard gameweek | `src/squadopt/application/scoreboard.py` | `tests/unit/test_build_scoreboard.py`, `tests/unit/test_scoreboard_basis.py` |
| `week_live_v1.md`, `week_live_v1.schema.json`, `week_live_v1.examples.json` | A member's gameweek live inputs and their display calculation (#1008) | The committed examples; `scripts/export_official_scoring_vectors.py` writes its synthetic weeks in this shape | `tests/unit/test_week_live_contract.py` |
| `league_device_plan_v1.md` | What a member's own browser needs to solve the one-week plan | `src/squadopt/application/device_plan.py`; solved by `web/src/features/league/device/`; `scripts/add_device_plan_inputs.py` and `scripts/export_device_plan_fixture.py` | `tests/unit/test_device_plan.py`, `tests/unit/test_device_plan_fixture.py`, `tests/unit/test_add_device_plan_inputs.py` |
| `league_publication_identity_v1.md` | The record that binds a league's members and retained history as one publication | `src/squadopt/contracts/league_publication_identity.py` | `tests/unit/test_league_publication_identity.py` |
| `football_point_accounting_v1.md` | Raw football point accounting for explicitly supplied moments (#1070) | `src/squadopt/contracts/football_point_accounting.py` | `tests/unit/test_football_point_accounting.py`, `tests/unit/test_football_point_accounting_native.py` |

## Word lists

| File | What it holds | Read by |
| --- | --- | --- |
| `honesty_words.json` | The plain-string honesty stems shared by the website and the package | `scripts/generate_honesty_stems.py`, which writes `src/squadopt/contracts/honesty_stems.py`; `web/src/testSupport/honesty.ts`; `tests/unit/test_honesty_words.py` |
| `quote_withheld_corpus.json` | A test corpus for the honesty words | `tests/unit/test_honesty_words.py`; `web/src/testSupport/honesty.test.ts` |
