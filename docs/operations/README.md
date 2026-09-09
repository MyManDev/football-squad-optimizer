# Operations

| Task | Procedure |
| --- | --- |
| Inspect discovered infrastructure and start the prepared API/worker deployment | [Operations inventory](../architecture/operations_inventory.md) |
| Create, verify and restore private backups | [Backup and recovery](../architecture/backup_recovery.md) |
| Produce the member publication for a week | [Weekly runbook](../weekly_runbook.md) |
| Understand opening capture/decision/settlement | [Opening-week runbook](../opening_week_runbook.md) |
| Deploy the static website | [Deployment runbook](../deployment_runbook.md) |
| Prepare and accept the separate advice API/worker | [Backend runbook](../backend_runbook.md) |
| Read the committed season summary | [2026-27 season ledger](../season_ledger_2026-27.md) |
| Understand storage responsibilities | [Persistence boundaries](../architecture/decisions/0005-persistence-boundaries.md) |
| Understand hosting responsibilities | [Backend hosting](../architecture/decisions/0006-backend-hosting.md) |

The complete member-publication week and `squadopt season tick` are different workflows.
Use the weekly runbook to identify the operation required; installing a scheduler around
tick alone does not establish automated member publication.

Record the exact code, capture, input/output artifacts and execution result for an operational
run. Confirm actual deployment, scheduling and restore evidence separately from source code
or an example configuration. Keep API, worker and publication write responsibilities separate.

New operational prose can live in this directory. Existing runbook paths remain stable until
a separately reviewed move updates every consumer. [All documentation](../README.md).
