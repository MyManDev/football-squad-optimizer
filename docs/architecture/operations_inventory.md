# Operational inventory and deployment acceptance

Investigated on 9 September 2026 during the enterprise transition. This records inspected
configuration, rather than assuming that undocumented infrastructure exists.

| Read-only inspection | Finding |
| --- | --- |
| GitHub repository environments | Only `cloudflare-pages` returned. |
| Repository variables | `CLOUDFLARE_PAGES_PROJECT=football-squad-optimizer`. |
| Repository secret names (values not read) | Cloudflare account ID and API token; no backend or backup credential name returned. |
| Recent GitHub scheduled runs | No scheduled runs returned by the schedule-event query. |
| Windows scheduled task names/actions matching squad, football or FPL | No matching task returned. This does not exclude an unrelatedly named task or another machine. |
| Azure CLI / Wrangler on this host | Not installed. No Azure subscription inventory was obtained. |
| Docker | Available; existing unrelated containers were left untouched. |
| Tracked deployment | Cloudflare publishes the static site. Azure Container Apps/NFS is a placeholder template; a live backend, shared mount and external backup remain unverified. |
| Weekly timing | Existing weekly runbook targets capture 2–3 hours before the deadline. No new age policy is introduced. |

The evidence does not establish an existing independent backup, backend server, alert
destination, accepted data-loss window or recovery-time commitment. The implementation
therefore provides explicit configuration, failure receipts and verification commands.
It does not buy infrastructure, add credentials or declare an untested recovery objective.

## One-command host deployment

`deploy/compose.yaml` preserves separate API and worker containers, one tested image,
one shared writable store and read-only publication/capture/handoff mounts. Copy
`deploy/backend.env.example` to an operator-owned file, set a tested image digest and
existing absolute paths, then run:

```text
docker compose --env-file /path/to/backend.env -f deploy/compose.yaml up -d
```

The image already carries its source commit; do not override it with an unrelated commit.
The store must allow image UID/GID 10001 to write. Missing bind sources are refused rather
than created as empty directories. API and metrics ports bind to host loopback; public
HTTPS ingress is an explicit host/proxy configuration. The mount and container filesystem
options follow the [Docker Compose service specification](https://docs.docker.com/reference/compose-file/services/).

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
No notification target was found; failure status and process exit are available to an
operator's scheduler without sending messages to an invented recipient.
