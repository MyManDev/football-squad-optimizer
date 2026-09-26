# Rebuild the Windows production machine

This is an owner-operated recovery recipe for a new x86-64 Windows PC. A complete
new-PC rebuild has **never been exercised**. The commands were checked against the
current repository scripts; that is not evidence of a successful disaster recovery.
Use a clean destination and the approved backend commit containing this recipe and
`scripts/backup_data.ps1`. Keep the old serving machine unchanged until recovery has
been accepted. This document does not authorize a live restart or a publication.

## 1. Tools and checkout

Install 64-bit Python **3.13**, Node.js **22**, Git for Windows, the GitHub CLI and
Cloudflare's `cloudflared`. The pinned Python environment is `constraints.txt`; the web
dependency versions are in `web/package-lock.json`. PowerShell **5.1** is sufficient.
Git 2.51.0.windows.1, Node 22.23.2 and GitHub CLI 2.97.0 were available when these
commands were checked; these are observations, not new version pins. The tunnel binary
has no repository version pin: record the installed version before relying on it.

Run from PowerShell after adding the installed tools to PATH:

```powershell
python --version
node --version
git --version
gh --version
winget install --id Cloudflare.cloudflared
cloudflared --version
git clone https://github.com/MyManDev/football-squad-optimizer.git C:\squadopt
Set-Location C:\squadopt
git switch --detach <approved-backend-commit>
python -m venv .venv
.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[api,dev]"
Push-Location web
npm ci
npx playwright install chromium
Pop-Location
```

Require Python 3.13 and Node 22 in the first two outputs. Replace angle-bracket
placeholders before running. `py` is not assumed to be installed. The fresh install
sequence on a new PC is **never exercised**; local tests used an existing environment.

## 2. Restore the five irreplaceable trees

Choose the existing backup directory on a second physical drive. Reparse paths,
including many synced-folder roots, are refused. It must be outside every checkout/worktree.
In this clean clone, restore the selected manifest's
entries, including each stamped conflict variant, to the original relative name:

```powershell
$backupRoot = '<existing-backup-directory>'
$latestManifest = Get-ChildItem -LiteralPath $backupRoot -Filter 'manifest-*.json' -File |
    Sort-Object Name -Descending | Select-Object -First 1
if (-not $latestManifest) { throw 'No backup manifest found.' }
$manifest = Get-Content -LiteralPath $latestManifest.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($tree in @('snapshots', 'ledger', 'handoffs', 'advice_records', 'entries')) {
    New-Item -ItemType Directory -Force (Join-Path 'data' $tree) | Out-Null
}
foreach ($record in $manifest.files) {
    $restoredPath = Join-Path 'data' $record.path
    New-Item -ItemType Directory -Force (Split-Path -Parent $restoredPath) | Out-Null
    Copy-Item -LiteralPath (Join-Path $backupRoot $record.destination_path) -Destination $restoredPath
}
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\backup_data.ps1 -Destination $backupRoot -Verify -Manifest $latestManifest.Name
```

The example selects the newest manifest; select an older named recovery point if needed
and pass that same name to verification. Stop here if verification is nonzero. Do not restore runtime queues, caches, PID files
or jobs. The new backend creates its own runtime store. Do not treat a clone as a data
backup: Git does not contain these five trees. First real backup and real restore are
**never exercised**; only disposable fixture restores have passed. Registering a daily
backup is a separate owner action using the line in the
[deployment runbook](deployment_runbook.md#back-up-irreplaceable-data).
The daily backup schedule has **never been registered**.
After an intentional older-point restore, a later backup can report newer records
missing against its latest manifest. Inspect the loss list before using `-AcceptMissing`;
that acknowledgement writes a new manifest and keeps all old backup files. Without it,
new files still copy but the loss alarm stays nonzero and no new manifest is written.

## 3. Restore the exact published tree and derived inputs

The backend also needs the published `web/public/data` tree. Download the retained
`site` artifact from the successful main-push CI run for the currently accepted
publication, into a new empty directory. Do not rebuild from today's upstream data.

```powershell
gh auth login
gh run download <accepted-main-ci-run-id> --repo MyManDev/football-squad-optimizer --name site --dir C:\squadopt-site-restore
node web/scripts/check-deployment-assets.mjs C:\squadopt-site-restore
Move-Item -LiteralPath web\public\data -Destination C:\squadopt-checkout-data-retained
Copy-Item -LiteralPath C:\squadopt-site-restore\data -Destination web\public -Recurse -Force
```

Both named recovery directories must be new; the move preserves the clone's bundled
data so it cannot leave stale files mixed into the restored publication. These steps
are for the clean recovery checkout only. CI retains the `site` artifact for seven days.
The same accepted tree is committed under `web/public/data` at its accepted release tag;
use the [deployment runbook](deployment_runbook.md) to find the matching run and tag.
If the artifact has expired, recover that exact tagged tree or stop for an owner-approved
regeneration. This
new-PC artifact recovery is **never exercised**. The readiness check must confirm that
the restored publication and capture agree before the machine serves requests.
All six checks must pass: `capture_context` (the published capture under `data/snapshots`
with its matching handoff under `data/handoffs`), `league_tree`, `cache_store`,
`league_tree_matches_capture`, and the two that need the workers running, `worker_heartbeat`
and `queue_wait`.

This recovery checkout has a detached HEAD and a replaced tracked `web/public/data` tree.
`scripts/release/restart_backend.ps1` requires a clean checkout on `develop` and refuses
both conditions. Before the next regular release, preserve the accepted recovered tree
and return the checkout to a clean `develop` through the normal release procedure.

`scripts/backup_data.ps1` does not back up the generated `artifacts/` directory or the reproducible public
archive `data/raw`. Restore the exact accepted Top 100 and rotation table/manifest
pairs into `artifacts/` from retained publication outputs, or follow the existing
[weekly recipe](weekly_runbook.md) for an approved regeneration. Missing evidence is
not replaced with invented inputs: relevant switches can remain unavailable. The
launcher's club-news default is the committed **example fixture**, not a real club
source. A complete recovery of these optional inputs is **never exercised**.

## 4. Tunnel identity and site build setting

Use the already documented `%USERPROFILE%\.cloudflared` location: `config.yml`, the
existing tunnel's `<TUNNEL-UUID>.json` credentials, and the login certificate where the
existing setup uses one. Recover them through the owner's existing secure procedure;
none belongs in Git or an issue. Copy the repository's
[configuration example](../deploy/cloudflared/config.example.yml) only if reconstructing
the configuration, substituting the existing tunnel UUID and credential path. Do not
create another tunnel or change DNS merely because the PC changed.

```powershell
cloudflared tunnel ingress validate
cloudflared tunnel ingress rule https://squadopt-api.mymandev.com/metrics
cloudflared tunnel ingress rule https://squadopt-api.mymandev.com/ready
gh variable get ADVICE_API_ORIGIN --repo MyManDev/football-squad-optimizer
```

The `/metrics` check must report the `http_status:404` rule and the `/ready` check the
`http://127.0.0.1:8000` rule: metrics never leave the machine, readiness is served.
CI maps `ADVICE_API_ORIGIN`
to `VITE_ADVICE_API_ORIGIN` when it builds the site. Setting the variable does not change
an already published bundle; a different backend origin needs a normal approved site
release. Only if the hostname changed, set the new public value with
`gh variable set ADVICE_API_ORIGIN --repo MyManDev/football-squad-optimizer --body "<new-public-origin>"`.
Reusing the current origin requires no configuration write or site deployment for this recovery.
Credential transfer and tunnel operation on a replacement PC are **never exercised**.

## 5. Start, inspect, then register the watch

After the owner has coordinated cutover so only the intended machine serves this
tunnel, start from the new checkout in a PowerShell console:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_backend_at_logon.ps1 -DryRun
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_backend_at_logon.ps1 -Watch
```

The watch keeps that console running. It starts missing components and checks every
60 seconds; it does not repair an unhealthy but still-live backend. The current
defaults are six workers, loopback port 8000 and the documented tunnel/connector label.
In another PowerShell console at the same checkout:

```powershell
.venv\Scripts\python.exe -m scripts.backend_status --days 1
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_backend_at_logon.ps1 -Register
```

Require `READY`, matching capture/tree checks, and successful public health before
accepting recovery. Missing metrics are unknown, not zero. `-Register` writes the
current user's Startup shortcut with `-Watch`; it starts at the next logon, not now.
The PC must remain awake and logged in. Watch behavior is covered by mocked tests;
replacement-PC startup and logon persistence are **never exercised**.
`-Register` has **never been exercised on any machine**.

## 6. Prove what the member can read

Use the exact `generated_at_utc` from `web/public/data/league/members.json` in the accepted
publication tree. The verifier requires equality, including for a same-tag re-dispatch.
Do not use the recovery time (restoring a PC does not republish the site):

```powershell
.venv\Scripts\python.exe scripts/release/verify_live.py <accepted-generated-at-UTC>
Push-Location web
$env:LIVE_BASE_URL = 'https://squadopt.mymandev.com'
$env:LIVE_SMOKE_COMPUTE = '1'
npx playwright test --config playwright.live.config.ts --workers=1
Pop-Location
```

This manual browser check covers desktop and phone. The optional compute check is a
GET only: a matching cached answer or `NOT_COMPUTED` is reported without starting a
solve. It does not prove that the new worker can finish a real request. Do not set
`SQUADOPT_BROWSER_SMOKE=1` for this recipe. Keep the commands' exit codes and reports as
recovery evidence. A complete restored-machine end-to-end run is **never exercised**;
accept it only after these checks pass on that machine and the owner verifies the
required inputs. Oracle provisioning remains a separate decision about account
availability and architecture parity.
