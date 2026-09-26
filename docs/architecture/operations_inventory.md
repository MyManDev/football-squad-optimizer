# Operational inventory and deployment acceptance

Investigated on 9 September 2026 during the enterprise transition. This records inspected
configuration, rather than assuming that undocumented infrastructure exists. The table is
that day's reading; where a row has changed since, the row says so and names the read that
shows it (last checked 26 September 2026).

| Read-only inspection | Finding |
| --- | --- |
| GitHub repository environments | Only `cloudflare-pages` returned. |
| Repository variables | `CLOUDFLARE_PAGES_PROJECT=football-squad-optimizer` on 9 September. Since 18 September also `ADVICE_API_ORIGIN=https://squadopt-api.mymandev.com` (`gh variable list`), which the site build in `.github/workflows/ci.yml` has passed as `VITE_ADVICE_API_ORIGIN` since #615 ([backend free hosting](../backend_free_hosting.md#3-tell-the-site-build-where-the-api-is)). |
| Repository secret names (values not read) | Cloudflare account ID and API token; no backend or backup credential name returned. |
| Recent GitHub scheduled runs | None on 9 September. Since #676 the `Backend uptime` workflow is scheduled (`*/15` in `.github/workflows/backend-uptime.yml`); `gh run list --event schedule` lists its runs, which land hours apart rather than every fifteen minutes (measured in [backend free hosting](../backend_free_hosting.md#recommendation)). |
| Windows scheduled task names/actions matching squad, football or FPL | No matching task returned. This does not exclude an unrelatedly named task or another machine. |
| Azure CLI / Wrangler on this host | Not installed. No Azure subscription inventory was obtained. |
| Docker | Available; existing unrelated containers were left untouched. |
| Tracked deployment | Cloudflare publishes the static site. Azure Container Apps/NFS is a placeholder template. Since #602 the live backend runs on the owner's Windows PC behind the `squadopt-api` Cloudflare Tunnel ([backend free hosting](../backend_free_hosting.md)), not on this template or on Compose; a shared mount on another host and an external backup remain unverified. |
| Weekly timing | Existing weekly runbook targets capture 2–3 hours before the deadline. No new age policy is introduced. |

On 9 September the evidence did not establish an independent backup, backend server, alert
destination, accepted data-loss window or recovery-time commitment. Since then a backend
server (the owner's PC) and a backend alert exist, as the rows above and the last section
say; the repository still establishes none of the other three. The implementation therefore
provides explicit configuration, failure receipts and verification commands.
It does not buy infrastructure, add credentials or declare an untested recovery objective.

## One-command host deployment

The start procedure for `deploy/compose.yaml` lives in the
[backend runbook](../backend_runbook.md#one-host-with-compose); this section records what to
verify once it is up. The image already carries its source commit; do not override it with an
unrelated commit. The mount and container filesystem options follow the
[Docker Compose service specification](https://docs.docker.com/reference/compose-file/services/).

Verify API `/health`, `/ready`, `/metrics`, and worker port 9091 `/health` and `/metrics`.
Worker solve/job counters belong to the worker listener; API cache/request counters belong
to the API. Process liveness alone does not prove input readiness or queue progress. The
queue probe now checks independent-descriptor lock exclusion/release as well as create,
link and mtime semantics. Actual cross-container and restart durability remain acceptance
checks on the selected host. Container health reports do not themselves restart unhealthy
processes; the restart policy applies when a process exits.

For rollback, select the previously tested digest in the same environment file and use
the same command, after draining old queue writers. Keep original inputs, retained capture
handoffs and backup receipts. Never run mixed pre-fencing and fenced queue writers on one
store. Do not remove volumes or store directories to obtain a clean health result.

## Azure prerequisite found during research

The current [Azure storage-mount documentation](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)
states that Container Apps supports classic Azure Files shares, that NFS needs a custom
virtual network, and that NFS encryption in transit is unsupported. An encryption-required
NFS share can therefore fail to mount. Do not weaken a storage account's existing security
settings to make the placeholder template work. Resolve that hosting/storage choice and
test queue locking, replacement persistence and read-only mounts before public ingress.

## Recovery policy remains explicit

The backup tool preserves complete selected roots and does not prune. For initial operation,
take a verified independent copy after each successful capture/publication and before a
deployment that changes persistent state. This is a proposed operating procedure, not a
claim that such a schedule is running. Record the actual interval between protected copies
and time an isolated restore before setting a recovery-time commitment. The existing site's
seven-day CI artifact retention is not a backup policy for private ledger/advice records.
`scripts/backup_data.ps1` (#670) takes an additive, verified copy of the five data trees; the
repository does not record whether it runs on a schedule.

No notification target was found on 9 September. Since #676 there is one, for the backend
only: a failed `Backend uptime` check opens a single `backend-down` issue in this repository
and recovery closes it, so the alert reaches whoever subscribes to the repository's issue
notifications. Nothing else sends a message; other failure status and process exit are
available to an operator's scheduler without sending messages to an invented recipient.
