# Opening one-week LLMOPT

The owner controls two separate live openings. The first is a short provider check that ends with the master setting at zero. A sustained one-week opening requires a subsequent owner decision. Both use the existing API and worker. Three-week planning continues through the ordinary workflow. [Release controls and defaults](../architecture/decisions/0024-llmopt-release-control.md)

**Release prerequisite.** Keep the master at zero until the published site bundle, API, worker, Compose definition and release utility all include the per-window changes from #1481. A tab opened with the earlier site can still send a run ID for three weeks. The updated API refuses new work on a cache miss with HTTP 409 `LLMOPT_VNEXT_DISABLED`. An old three-week plan catalogue can also receive HTTP 422 `VALIDATION_FAILED` during chat. The tab can show a failed calculation or message. Reload the tab to obtain the new site before trying again. [Window controls](https://github.com/MyManDev/football-squad-optimizer/pull/1481)

A fresh draft without a selected window starts at one week. During a one-week opening, its first chat message uses the one-week prompt and schema even if the text asks for three weeks. Select **3 weeks** before writing for the three-week prompt. The resulting draft's window governs confirmation.

## Short provider check

1. Start with both release settings at zero. Follow **Open one week on the host** and **Check the current grants** below. The grant applies to every eligible member on the live site for the duration of the check.
2. Obtain the owner's approval now for the live provider check. On the live member page, use the checklist's current-squad setup and send its two messages per provider. Check the ordinary rule and the selected card against the displayed results. Use **Delete** to clear the browser credential between providers.
3. At the end of the check, including after an error, follow **Close one week again** and verify the closed capability response. Record the applicable checklist rows. A later sustained opening repeats the opening and grant checks after the owner's decision.

The owner enters their existing credential in **Your model** for each provider being tested. The browser sends it to the selected provider. The site supplies the request through `/api/v1/llmopt/prompt` and checks the reply through `/api/v1/llmopt/check`. Both site routes are keyless. Record the provider, model ID, outcome and a short error code. A provider without an existing credential or eligible model stays **not run**. The checklist covers all eight adapters, including an owner's local endpoint when available. [Provider acceptance checklist](llmopt_provider_acceptance.md) · [Key handling](../architecture/decisions/0017-llmopt-own-key.md)

## Open one week on the host

Use a release whose site, API image and Compose file all include the separate three-week setting. The documented Contabo installation uses project `squadopt` under `/root/squadopt`. Its private environment is `/root/squadopt/.env`. The release tool combines `repo/deploy/compose.yaml` with the active `/root/squadopt/compose.artifacts.yaml`, which supplies artifact and club-news mounts to both services. The generic single-host example uses one Compose file. On the release-managed host, keep both files in the command. [Active host layout](../../deploy/weekly-schedule/README.md#the-advice-backend) · [Release tool](../../scripts/release/vm_football_release.py) · [Generic single-host layout](../backend_runbook.md#one-host-with-compose)

Obtain the owner's approval now for this edit, for either the short test or the sustained opening. In a private editor, update each existing entry in the active environment file. Append any missing entry on its own line. Leave exactly one active assignment per name. Preserve the file's permissions and other entries.

```dotenv
SQUADOPT_BACKEND_LLMOPT_VNEXT=1
SQUADOPT_BACKEND_LLMOPT_VNEXT_THREE_WEEK=0
SQUADOPT_BACKEND_THREE_WEEK_PATHS=0
SQUADOPT_BACKEND_TRANSFER_PACKAGES=0
SQUADOPT_BACKEND_PACKAGE_GATE=0
```

The shared Compose environment passes the first two values to both containers. The other three default to zero in the application. If a site-specific service override sets any of those three, its effective value must also be zero. Use the same operator shell for the following commands. The function lets the environment file supply the release switches even if those names were exported by the shell. [Compose services](../../deploy/compose.yaml) · [Environment example](../../deploy/backend.env.example) · [Runtime settings](../../src/squadopt/platform/backend_runtime.py)

```sh
cd /root/squadopt
squad_compose() (
  unset SQUADOPT_BACKEND_LLMOPT_VNEXT SQUADOPT_BACKEND_LLMOPT_VNEXT_THREE_WEEK
  unset SQUADOPT_BACKEND_THREE_WEEK_PATHS SQUADOPT_BACKEND_TRANSFER_PACKAGES SQUADOPT_BACKEND_PACKAGE_GATE
  docker compose -p squadopt --env-file /root/squadopt/.env \
    -f /root/squadopt/repo/deploy/compose.yaml \
    -f /root/squadopt/compose.artifacts.yaml "$@"
)
worker_idle() {
  queue_metrics=$(curl -fsS http://127.0.0.1:8000/metrics) || return 1
  printf '%s\n' "$queue_metrics" |
    awk '$1 == "advice_jobs{status=\"running\"}" { idle = ($2 == "0"); found = 1 }
         END { exit !(found && idle) }'
}
```

Obtain the owner's approval now to recreate the two containers. Check for a running job immediately before recreating. The worker has a 180-second shutdown grace period. If the gauge is missing, unreadable, or above zero, wait and check again. [Queue status gauges](../../src/squadopt/platform/advice_observability.py) · [Worker grace period](../../deploy/compose.yaml)

```sh
worker_idle && squad_compose up -d --no-deps --force-recreate api worker
squad_compose ps api worker
```

A plain `restart` reuses each container's original environment. Recreation reads the updated values and keeps the existing store. Check API readiness, worker health and the five release values in each container. The two HTTP commands use the host's documented loopback ports.

```sh
curl -fsS -o /dev/null http://127.0.0.1:8000/ready
curl -fsS -o /dev/null http://127.0.0.1:9091/health
for service in api worker; do
  printf '%s\n' "$service"
  squad_compose exec -T "$service" python -c '
import os
for name in ("LLMOPT_VNEXT", "LLMOPT_VNEXT_THREE_WEEK", "THREE_WEEK_PATHS", "TRANSFER_PACKAGES", "PACKAGE_GATE"):
    key = "SQUADOPT_BACKEND_" + name
    print(key, os.environ.get(key, "0"), sep="=")
'
done
```

## Check the current grants

For a published league member, use `GET /api/v1/leagues/{league}/capabilities`. For a forwarded team on a deployment that already serves public entries, use `GET /api/v1/public/leagues/{league}/entries/{entry}/capabilities`. Use league `0` for a standalone `/entry/{entry}/llmopt` page. Choose the league and entry already open on the site. Match `league_id`, `season`, `gameweek` and `capture_snapshot_id` to that page's league and squad publication. A different capture, including an older archive, cannot grant new work for the page. [Capability schema](../contracts/league_capabilities_v1.schema.json) · [Page capture check](../../web/src/features/league/advice/adviceCapabilities.ts)

The release tool uses the following IDs for its published league probe. Substitute the actual page IDs when observing a different member. The second command applies when the page obtains its team through the public route.

```sh
league_id=352490
entry_id=313686
show_grants() {
  curl -fsS "http://127.0.0.1:8000$1" | python3 -c '
import json, sys
doc = json.load(sys.stdin)
for field in ("league_id", "season", "gameweek", "capture_snapshot_id", "llmopt_vnext", "llmopt_vnext_three_week", "three_week_paths", "transfer_packages"):
    value = doc.get(field, "absent")
    print(field, str(value).lower() if isinstance(value, bool) else value, sep="=")
'
}
show_grants "/api/v1/leagues/$league_id/capabilities"
show_grants "/api/v1/public/leagues/$league_id/entries/$entry_id/capabilities"
```

| In the current capability response | One week open | After rollback |
| --- | --- | --- |
| `llmopt_vnext` | `true` | absent |
| `llmopt_vnext_three_week` | absent | absent |
| `three_week_paths`, `transfer_packages` | both absent | both absent |

Obtain the owner's approval now before confirming a live test plan, which can submit work. On the published member's `/league/{league}/members/{entry}/llmopt` page, select **1 week** and confirm a fresh draft. A compatible one-week device can compute locally after checking the current grant and inputs. Other eligible one-week requests can use the server. For **3 weeks**, a fresh draft uses the ordinary main plan, individual prices and combined plan as applicable. [Confirmation logic](../../web/src/features/league/llmopt/releaseRun.ts) · [Opening observation](llmopt_one_week_observation.md)

## Close one week again

Obtain the owner's approval now for the turn-off edit. In the same private `/root/squadopt/.env`, replace each existing entry and append any missing one so each name appears exactly once.

```dotenv
SQUADOPT_BACKEND_LLMOPT_VNEXT=0
SQUADOPT_BACKEND_LLMOPT_VNEXT_THREE_WEEK=0
SQUADOPT_BACKEND_THREE_WEEK_PATHS=0
SQUADOPT_BACKEND_TRANSFER_PACKAGES=0
SQUADOPT_BACKEND_PACKAGE_GATE=0
```

Obtain the owner's approval now to recreate the two containers for turn-off. Run `worker_idle && squad_compose up -d --no-deps --force-recreate api worker`. Wait and check again if a job is running or the gauge is unavailable. The worker has a 180-second shutdown grace period. Repeat the readiness, worker and current capability checks above.

After **every release rollback**, including automatic recovery from a failed activation, re-read the five entries in the active environment file and repeat the five-value check in **both** running containers. An absent entry defaults to zero. After turn-off, expect five zeros and absent planning grants. If the values differ, leave the opening pending. Any corrective edit or container recreation requires the owner's approval at that time.

Answers cached while open stay at their calculation keys. With the control closed the API serves them with `plan_data_id` stripped. Receipts under `store/cache/plan-provenance/` and the ledger at `store/runs/ledger.json` stay on disk. Previously admitted work can finish under its recorded settings. A closed run can read its admitted job but cannot open a new advanced stage. Server cache reads still require a matching current capture.

Reload a tab with a completed plan and verify it remains readable. A member holding a priority or total-limit draft sees the notice and a disabled **Compute plans**. Clearing the grouped terms enables the ordinary flow. Count a closed-window `REPLY_REFUSED` with rejected model replies during observation. [Run and rollback contract](../contracts/llmopt_run_v1.md#workflow-selection) · [Rejection counts](llmopt_one_week_observation.md)
