# Operations

| Task | Procedure |
| --- | --- |
| Review product security findings and the independent backend/publication workstream | [Product security workstream](product_security.md) |
| Inspect discovered infrastructure and start the prepared API/worker deployment | [Operations inventory](../architecture/operations_inventory.md) |
| Create, verify and restore private backups | [Backup and recovery](../architecture/backup_recovery.md) |
| Observe and resume a journaled weekly run | [Installed weekly operations](../architecture/weekly_operations.md) |
| Reproduce advice load and inspect measured resource use | [Capacity acceptance](../architecture/advice_capacity.md) |
| Produce the member publication for a week | [Weekly runbook](../weekly_runbook.md) |
| Understand opening capture/decision/settlement | [Opening-week runbook](../opening_week_runbook.md) |
| Deploy the static website | [Deployment runbook](../deployment_runbook.md) |
| Measure whether FPL answers Cloudflare's network before an FPL forwarder is built | [FPL forwarder probe](../fpl_forwarder_probe.md) |
| Prepare and accept the separate advice API/worker | [Backend runbook](../backend_runbook.md) |
| Move a gameweek's inputs and football bundle to the backend VM, prove them beside the live project, then switch with a kept rollback | [VM release package](vm_release_package.md) |
| Run the advice API/worker on the owner's PC behind a Cloudflare Tunnel, and the zero-cost hosting comparison | [Backend free hosting](../backend_free_hosting.md) |
| Read the committed season summary | [2026-27 season ledger](../season_ledger_2026-27.md) |
| Understand storage responsibilities | [Persistence boundaries](../architecture/decisions/0005-persistence-boundaries.md) |
| Understand hosting responsibilities | [Backend hosting](../architecture/decisions/0006-backend-hosting.md) |
| Compare where the advice backend could run instead of the owner's PC (proposed, undecided) | [Hosting options](../architecture/decisions/0009-advice-backend-hosting-options.md) |
| See every advice backend route, who calls it and what replaces it when the backend is retired (#988 route 1) | [Advice backend endpoints](advice_backend_endpoints.md) |
| Capture club news within its model-call allowance, and read how FPL player facts and coach news reach the football forecast and the decision | [FPL facts, coach news and football decisions](fpl_news_decisions.md) |
| Inspect composite family identities and runtime dispatch (`src/squadopt/prediction/football_capabilities.py:43`) | [Composite runtime contract](football_composite_runtime.md) |
| Construct explicit joint participation states for phase allocation | [Phase participation coupling](football_phase_coupling.md) |
| Compose flag, LOAD and verified evidence on one weekly minute law | [Joint weekly law](football_joint_week_law.md) (`src/squadopt/prediction/football_joint_week_law.py:370`) |
| Compose a complete declared roster across captured fixture weeks | [Composite weekly population](football_composite_weeks.md) (`src/squadopt/prediction/football_composite_weeks.py:366`) |
| Prepare the standalone observed non-PL record workload model | [Observed workload contract](football_observed_load.md) (`src/squadopt/prediction/football_observed_load.py:295`) |
| Prepare the optional first-week categorical flag/minute forecast from original retained capture pairs | [Retained flag forecasts](retained_flag_forecasts.md) |
| Check why the official injury source is disabled for production, and seal a prepared football decision bundle | [Official injury discovery and current club-news selection](official_injury_discovery.md) |
| Prepare historical public-revision facts for experimental phase training | [Phase training from original revisions](phase_training_replay.md) |
| Prepare an explicitly defined point XI from native starter probabilities | [Club-unit point projection](football_unit_point.md) |
| Export and restore compact phase parameters with explicit byte receipts (`src/squadopt/prediction/football_phase_serving.py:304`, `src/squadopt/prediction/football_phase_serving.py:354`) | [Compact phase serving parameters](football_phase_serving.md) |
| Prepare typed historical unit replay with explicit 2025-26 training release (`src/squadopt/features/football_unit_inputs.py:201`, `src/squadopt/prediction/football_unit_strength.py:343`) | [Historical unit replay](football_unit_replay.md) |
| Fit the explicit source absence and residual missingness version (`src/squadopt/prediction/football_unit_strength.py:343`) | [Unit source missingness](football_unit_source_missingness.md) |
| Fit exact physical unit exposures with a separate causal duration forecast (`src/squadopt/features/football_unit_inputs.py:382`, `src/squadopt/prediction/football_unit_strength.py:343`) | [Unit physical exposure](football_unit_physical.md) |
| Fit raw player residuals with shared FM context and explicit exposure pooling (`src/squadopt/prediction/football_unit_strength.py:343`) | [Unit player residual pooling](football_unit_pooled_identity.md) |
| Export and read compact pooled v4 unit parameters with a distinct inference receipt (`src/squadopt/prediction/football_unit_serving.py:425`, `src/squadopt/prediction/football_unit_serving.py:516`) | [Compact unit inference](football_unit_serving.md) |
| Compose one complete fixture from final minute marginals and current compact family models (`src/squadopt/prediction/football_composite_core.py:617`) | [Composite fixture inference](football_composite_core.md) |
| Prepare a historical score training record with declared source clocks and explicit released-season opt-in (`src/squadopt/features/football_score_replay.py:121`) | [Score replay contract](football_score_replay.md) |
| Inspect the separately certified bounded fallback for a score fit (`src/squadopt/prediction/football_score_state.py:298`) | [Score solver receipt](football_score_solver.md) |
| Inspect the explicit forecast-clock approximation for native player intervals (`src/squadopt/features/football_score_projection.py:174`) | [Score interval projection](football_score_projection.md) |
| Export and read compact score-process parameters (`src/squadopt/prediction/football_score_serving.py:185`) | [Compact score serving](football_score_serving.md) |
| Inspect the separate four-channel tactical input, fit and allocation contract (`src/squadopt/prediction/football_observed_tactical.py:181`) | [Observed tactical context](observed_tactical_context.md) |
| Fit the distinct conditional recipient-only model (`src/squadopt/prediction/football_observed_tactical_recipients.py:134`) | [Observed tactical recipient training](observed_tactical_recipient_training.md) |
| Retain and restore compact observed-tactical recipient parameters (`src/squadopt/prediction/football_observed_tactical_serving.py:329`) | [Compact observed tactical recipients](observed_tactical_serving.md) |
| Verify the retained composite recipe and reproject first-week news (`src/squadopt/live/football_composite_basis.py:784`) | [Retained composite basis](football_composite_basis.md) |
| Cut a release, deploy a `site-*` tag and verify the live site with the release recipe (`scripts/release/ship.sh`, `deploy.sh`, `verify_live.py`, `clean_body.py`) | [Release in one command](../deployment_runbook.md#release-in-one-command) |
| Restart a running backend on the code of the live release (`scripts/release/restart_backend.ps1`), or start a stopped one from that release | [The release window](../deployment_runbook.md#the-release-window-is-closed-to-develop) and [a stopped backend](../deployment_runbook.md#a-stopped-backend-starts-from-the-release) |
| Register or remove the `SquadOptBackendWatch` scheduled task, which starts the backend and its tunnel at logon and restarts a missing component | [Backend free hosting, starting the backend](../backend_free_hosting.md#1-start-the-backend) |
| Register the `SquadOptDataBackup` scheduled task, which backs up the private data trees daily with `scripts/backup_data.ps1` | [Back up irreplaceable data](../deployment_runbook.md#back-up-irreplaceable-data) |

## Workflows

| Workflow | Runs on | What it does |
| --- | --- | --- |
| [`CI`](../../.github/workflows/ci.yml) | Pull requests and pushes to `develop` and `main`, the `develop` merge queue, manual dispatch | The five Python gates on Python 3.11 and 3.13, the container build and smoke, and the web checks; uploads the `site` artifact |
| [`Deploy Pages`](../../.github/workflows/deploy-pages.yml) | A completed CI run, or a manual dispatch with a `site-*` tag | Deploys a pull request preview, or the tagged production artifact after its checks |
| [`Backend uptime`](../../.github/workflows/backend-uptime.yml) | A schedule every 15 minutes, or a manual dispatch | Probes the backend's health and readiness and opens or closes a `backend-down` issue |
| [`Windows scripts`](../../.github/workflows/windows-scripts.yml) | Pull requests and pushes that touch the PowerShell scripts, the release recipe or their tests | Parses the PowerShell scripts and runs their tests on Windows |
| [`Deploy FPL probe`](../../.github/workflows/deploy-fpl-probe.yml) | Manual dispatch from the default branch | Deploys or deletes the FPL probe Worker ([FPL forwarder probe](../fpl_forwarder_probe.md)) |

The complete member-publication week and `squadopt season tick` are different workflows.
Use the weekly runbook to identify the operation required; installing a scheduler around
tick alone does not establish automated member publication.

Record the exact code, capture, input/output artifacts and execution result for an operational
run. Confirm actual deployment, scheduling and restore evidence separately from source code
or an example configuration. Keep API, worker and publication write responsibilities separate.

New operational prose can live in this directory. Existing runbook paths remain stable until
a separately reviewed move updates every consumer. [All documentation](../README.md).
