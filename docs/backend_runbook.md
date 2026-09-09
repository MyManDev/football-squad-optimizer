# Advice backend runbook

The static site's runbook is [deployment_runbook.md](deployment_runbook.md); this is the other
deploy surface. They fail independently on purpose: with the backend down or absent the site is
the static site, byte for byte ([ADR 0006](architecture/decisions/0006-backend-hosting.md)).

**Nothing here is a deployment.** No paid resource is created by reading it, and the API is not
exposed to the internet by running it locally. The hosting decision — Azure Container Apps, one
replica, two containers, a durable Azure Files NFS share — is recorded in ADR 0006 and is not
re-decided here.

The definition of that topology now exists, as
[`deploy/containerapp.yaml`](../deploy/containerapp.yaml), and **applying it creates paid
resources**. This repository does not establish that these Azure prerequisites exist. No deployment or
cloud mount acceptance is claimed by the local preparation command below.

## The two commands

One image, two processes. Only the api gets ingress; the worker has no listener.

```bash
uvicorn --factory squadopt.api.runtime:build_app --host 0.0.0.0 --port 8000
```

```bash
python -m squadopt.platform.advice_worker
```

The worker takes `--max-jobs` (stop after N, for a one-shot run), `--idle-seconds` and
`--max-attempts`. It stops on SIGTERM or SIGINT **after** the job in hand finishes, so a
container stop costs nobody their solve.

## Configuration

Every value is server-side. A request names a league, a member, a strategy and a window; it
never names a path, an artifact root, or anything else about this table.

Two mounts. Only the store is written, so only the store is mounted ReadWrite; what ops
publishes is mounted ReadOnly.

```bash
# The one shared ReadWrite mount. jobs/, cache/, specs/ and probe/ are derived from it, so
# the api and the worker cannot be pointed at two stores that agree about nothing. It must
# already exist: the backend never creates it, because a process that creates its own store
# has quietly accepted a directory nobody mounted.
#
# A subdirectory of the mount rather than its root: a share root's mode and owner belong to
# the platform and may not be ours to set, while a subdirectory always is, and the runtime is
# uid 10001. See "Preparing the shared mount".
SQUADOPT_BACKEND_STORE_ROOT=/mnt/squadopt-store/store

# What ops publishes, all three on one ReadOnly mount. The read side answers "is this league
# connected" from this tree and never from an upstream call.
SQUADOPT_BACKEND_SITE_DATA_ROOT=/mnt/squadopt-inputs/site/data

# Captures and their projection handoffs. The newest live capture is selected first and
# must have its own matching handoff. An invalid newest pair makes the context unavailable;
# the resolver does not search older captures for a usable pair. No redeploy is needed.
SQUADOPT_BACKEND_SNAPSHOT_ROOT=/mnt/squadopt-inputs/snapshots
SQUADOPT_BACKEND_HANDOFF_ROOT=/mnt/squadopt-inputs/handoffs

# An allowlist, never a wildcard (ADR 0006). Empty means no cross-origin access at all.
# Both published hostnames, canonical first: squadopt.mymandev.com is the address members
# open, and the origin their browsers send. Keep it in step with SITE_ORIGINS in
# src/squadopt/platform/backend_runtime.py — a test asserts this line matches it.
SQUADOPT_BACKEND_ALLOWED_ORIGINS=https://squadopt.mymandev.com,https://squadopt.pages.dev

# Part of every answer's identity. An image carries no .git, so the build stamps it in;
# without it the backend refuses to fill a cache it could not name.
SQUADOPT_REPOSITORY_COMMIT=<40 hex>

# Optional.
SQUADOPT_BACKEND_SEASON=              # otherwise inferred from the capture
SQUADOPT_BACKEND_RATE_LIMIT=30        # per window, per client address and per (capture, entry)
SQUADOPT_BACKEND_RATE_WINDOW_SECONDS=60
```

The ops process does not move. Captures, decisions, settles and site builds stay on the machine
that owns the ledger; the backend **reads** what ops publishes and never writes it.

## Before ingress: the store probe

ADR 0006 requires the mount's primitives to be proven, not assumed. `/ready` reports
`cache_store: false` until `probe_store` has shown, on the configured path, that `O_EXCL`
creates exactly once, that `os.link` creates but refuses to replace, that a refreshed mtime is
observable, and that this process's own write appears in the directory every mounter reads.

One check is not a syscall. **The store root must already exist**, and the probe will not
create it. Every other primitive passes just as happily on a container's own ephemeral disk, so
a `docker run` that forgot its `--volume` would otherwise get a green probe on storage that
disappears at the next restart. The image therefore neither creates the directory nor defaults
the variable that names it: a forgotten volume fails at configuration, a mistyped path fails at
the probe.

That is a guard, not a proof. An existing directory can still be ephemeral, private to one
container, or a bind mount of a scratch path — the check catches the common shape of the
mistake and nothing more.

**What is verified, and what is not.** The container image is now built and exercised on every
commit: CI's `container (linux/amd64)` job builds it and runs
`tests/integration/test_backend_container.py`, which starts the api and the worker as two
containers from that one image over a shared volume and takes one request through to a cached
answer. **The durable mount is still unverified.** The probe has never run against an Azure
Files NFS share, no replica has been replaced, and a shared local volume is not evidence about
a cloud filesystem. That half is open work and must not be reported as done.

A pass is held for thirty seconds, not for ever. A store can stop working after it started, and
a gate that cached its first success would keep reporting a mount that has since gone away. A
failure is never cached, so a mount that arrives late brings the service up without a restart.
Each probe cleans up after itself, so the periodic re-checks do not grow the store.

The worker asks the same gate **before every round**, not only at startup: while it says no, no
job is claimed and none is recovered, and the loop idles until the store answers again. Nothing
interferes with a computation already running.

**The probe gates work, not only the readiness page.** While it is failing the api answers
`503 NOT_READY` to a POST instead of writing a job onto a store that cannot hold it, and the
worker process exits non-zero at startup instead of spending its life claiming nothing while
the deployment looks healthy.

A failed probe keeps the service unready. There is **no** fallback to local disk: falling back
would trade a loud startup failure for a quiet correctness one, which is
[ADR 0005](architecture/decisions/0005-persistence-boundaries.md)'s trigger firing silently. If
the chosen mount cannot pass, that is the trigger — adopt the managed-store adapters
deliberately and record it, rather than working around it.

**What a green probe does and does not say.** It is evidence about the filesystem the process
that ran it is looking at. Persistence across a replica replacement, and visibility between two
containers, are properties of the deployment: they are answered by running the probe from *both*
containers against the same mount and by replacing a replica and looking again. A green probe on
a developer's laptop is evidence about that laptop. It is not a validation of an Azure Files NFS
mount and must never be reported as one.

## Readiness

`GET /ready` reports three checks and is ready only when all three hold:

| Check | False when |
| --- | --- |
| `capture_context` | no capture, no handoff for it, or the pair cannot be read |
| `league_tree` | ops has published no `league/members.json` under the site data root |
| `cache_store` | the store probe has not passed on this path — a root that does not exist counts, which is the common shape of a forgotten volume, though not proof of one |

Store and capture-context failures produce coded 503 responses on their applicable advice
paths. Missing league membership instead returns `404 LEAGUE_NOT_CONNECTED` on POST while
`league_tree` is false. Readiness is a combined dependency report, not a promise that every
unready state has the same HTTP response.

## A local two-process run

Two processes against one store — this is how to see the whole path work without
deploying anything.

```bash
python -m pip install -e ".[api,dev]"
mkdir -p .local/store          # the backend will not create its own mount
export SQUADOPT_BACKEND_STORE_ROOT="$PWD/.local/store"
export SQUADOPT_BACKEND_SITE_DATA_ROOT="$PWD/web/public/data"
export SQUADOPT_BACKEND_SNAPSHOT_ROOT="$PWD/data/snapshots"
export SQUADOPT_BACKEND_HANDOFF_ROOT="$PWD/data/handoffs"
export SQUADOPT_BACKEND_ALLOWED_ORIGINS=http://localhost:5173
```

```bash
uvicorn --factory squadopt.api.runtime:build_app --port 8000
```

```bash
python -m squadopt.platform.advice_worker
```

```bash
curl -fsS localhost:8000/ready
```

```bash
curl -fsS -X POST localhost:8000/api/v1/leagues/352490/entries/101/advice -H 'Content-Type: application/json' -d '{"strategy":"saf-puan","window":1}'
```

Poll `GET /api/v1/advice-jobs/{job_id}` until it is `completed`, then repeat the POST: the same
request now returns the stored document instead of starting a second solve.

Captures and the entry payloads inside them are local and personal; `data/snapshots/` and
`data/entries/` are gitignored and stay that way.

## Preparing the shared mount

A fresh mount — a docker named volume, an Azure Files share — arrives owned by root. The image
runs as **uid 10001, gid 10001**, and the backend will not create its own store root, so the
directory has to exist and be writable by that pair before the first start. This is one
directory and a targeted `chown`, never a blanket `chmod 777`: a world-writable shared store is
a different problem, not a smaller one.

The store root is deliberately a *subdirectory* of the mount rather than the mount root. A
share root's mode and owner belong to the platform and may not be ours to change; a
subdirectory always is, and the step below is then identical locally and on the host.

```bash
docker run --rm --user 0:0 --volume squadopt-store:/mnt/squadopt-store squadopt-backend \
  sh -c 'mkdir -p /mnt/squadopt-store/store && chown 10001:10001 /mnt/squadopt-store/store'
```

For Azure, an operator-owned Linux preparation host inside the VNet must already mount the
store share read-write. Before the first worker revision, an authorized administrator runs:

```bash
sudo install -d -o 10001 -g 10001 -m 0755 /mnt/squadopt-store/store
```

The mounted share must permit that ownership operation under its root-squash and access
configuration. If it does not, resolve the storage permission prerequisite before applying.
The API and worker run as uid 10001; do not assume an exec session in either can perform a
root-only bootstrap. Provisioning that preparation host or changing storage policy is outside
the release helper's scope.

Whatever the platform, the check afterwards is the same, and a broken mount is one command to
diagnose:

```bash
stat -c '%u:%g %a' /mnt/squadopt-store/store   # expect 10001:10001 755
```

## The image, and a local container run

```bash
docker build --platform linux/amd64 \
  --build-arg SQUADOPT_REPOSITORY_COMMIT="$(git rev-parse HEAD)" -t squadopt-backend .
```

The build **refuses** a missing or malformed commit rather than producing an image that fails
at request time: it is part of every answer's identity, and the image carries neither `.git`
nor `git` to ask.

A tag is not an identity. Record what was built, because a rollback needs the digest and an
operator needs to know which interpreter and which pins answered:

```bash
docker image inspect --format '{{.Id}} {{.Architecture}}/{{.Os}} {{.Size}}' squadopt-backend
docker run --rm squadopt-backend id            # expect uid=10001 gid=10001
docker run --rm squadopt-backend python -VV    # expect 3.13.x
docker run --rm squadopt-backend python -m pip freeze
```

The image is Python 3.13 while the package still supports 3.11, for one demonstrated reason:
the pinned set cannot be installed on 3.11 at all — `numpy==2.5.2` and `scipy==1.18.0` declare
`requires_python >=3.12`. An image that installs `constraints.txt` therefore runs 3.13, and
CI's `gates (py3.11)` keeps proving the declared-range floor.

Claim no more than that. The image holds the same package **versions** as `constraints.txt`;
it does not establish numerical equivalence with the environment the committed measurements
were recorded in, which was a different operating system. Comparing the two is a measurement
of its own, and none has been run.

**A release names a digest, not a tag.** `python:3.13-slim` is mutable, and so is any tag put
on the image built from it: a rebuild a month later can be a different base with the same
name. Record the digest of the image the container gate actually passed against, and deploy
that digest. The tag belongs in the build command and nowhere downstream of it.

Then the same two commands, in two containers, over one volume and read-only inputs:

```bash
docker volume create squadopt-store
docker run --rm --user 0:0 --volume squadopt-store:/mnt/squadopt-store squadopt-backend \
  sh -c 'mkdir -p /mnt/squadopt-store/store && chown 10001:10001 /mnt/squadopt-store/store'
docker run -d --name squadopt-api --publish 127.0.0.1:8000:8000 \
  --volume squadopt-store:/mnt/squadopt-store \
  --volume "$PWD/.local/inputs:/mnt/squadopt-inputs:ro" \
  --env SQUADOPT_BACKEND_STORE_ROOT=/mnt/squadopt-store/store \
  --env SQUADOPT_BACKEND_SITE_DATA_ROOT=/mnt/squadopt-inputs/site/data \
  --env SQUADOPT_BACKEND_SNAPSHOT_ROOT=/mnt/squadopt-inputs/snapshots \
  --env SQUADOPT_BACKEND_HANDOFF_ROOT=/mnt/squadopt-inputs/handoffs \
  squadopt-backend
docker run -d --name squadopt-worker \
  --volume squadopt-store:/mnt/squadopt-store \
  --volume "$PWD/.local/inputs:/mnt/squadopt-inputs:ro" \
  --env SQUADOPT_BACKEND_STORE_ROOT=/mnt/squadopt-store/store \
  --env SQUADOPT_BACKEND_SITE_DATA_ROOT=/mnt/squadopt-inputs/site/data \
  --env SQUADOPT_BACKEND_SNAPSHOT_ROOT=/mnt/squadopt-inputs/snapshots \
  --env SQUADOPT_BACKEND_HANDOFF_ROOT=/mnt/squadopt-inputs/handoffs \
  squadopt-backend python -m squadopt.platform.advice_worker
```

The automated form of exactly this — with synthetic inputs, no user captures — is the gate:

```bash
SQUADOPT_CONTAINER_SMOKE=1 SQUADOPT_CONTAINER_IMAGE=squadopt-backend \
  python -m pytest tests/integration/test_backend_container.py -q
```

It is opt-in because the full suite is the merge gate and a developer without a Docker daemon
must not be failed by it. It proves the packaging and the process/storage boundary: the pinned
stack on linux/amd64, both commands from one image, an api-written job computed by the worker
container, the answer surviving the api container's replacement, `docker stop` letting the
worker exit 0, and a forgotten volume refused rather than served from ephemeral disk. It is
evidence about a local volume and says nothing about a cloud filesystem.

## Prepare a release for Azure Container Apps

ADR 0006 remains one replica with two separate processes from one linux/amd64 image. The
canonical `deploy/containerapp.yaml` is JSON-compatible YAML: one template defines both
containers. The initial ingress is internal on port 8000. API/worker commands and persistence
boundaries do not change. The helper performs no login, image push, registry pull, Azure
query or deployment. Its local checks do not prove cloud readiness.

### Required operator infrastructure and inputs

Before apply, the owner must provide an existing Container Apps environment with custom VNet
access to Azure Files NFS, environment storage entries named `squadopt-store` (ReadWrite) and
`squadopt-inputs` (ReadOnly), a prepared store directory owned by 10001:10001, and published
inputs. Supply a pre-existing user-assigned managed identity with ACR pull access; the same
identity is attached to the app and referenced in its registry configuration. The helper does
not provision these resources, grant access, set up mounts, or price the deployment.

The operator workstation needs Python, Git, PowerShell 7 and a Linux/amd64 Docker daemon.
Fresh verification also needs the project's dev dependencies. Apply needs Docker, the Azure
CLI with its Container Apps extension, and the owner's existing authenticated Azure context.
The exact published `repository@sha256:digest` must already be present in local Docker
metadata. Publication/pull and authentication are separate owner actions; neither the helper
nor its generated apply script performs them.

Copy `deploy/backend-release.example.json` to `.pt/operator.json`, replace synthetic values,
and keep credentials out of it. The input contract is:

| Field | Required value |
| --- | --- |
| `resource_group`, `app_name`, `location` | Existing target group, valid app name and Azure region |
| `environment_id` | Full `Microsoft.App/managedEnvironments` resource ID |
| `registry_identity_id` | Full `Microsoft.ManagedIdentity/userAssignedIdentities` resource ID |
| `image` | Full ACR repository reference with a lowercase SHA256 manifest digest; tags are rejected |
| `allowed_origins` | Nonempty list of exact HTTPS origins, no path, credentials or wildcard |
| `operation` | `create` by default, or `update` for an existing app |

Unknown fields are rejected without printing their values. A digest is an operator input;
syntax validation does not prove the referenced image exists or belongs to this release.

### One local preparation command

From the clean worktree, with its dev environment installed:

```powershell
python deploy/prepare_backend_release.py --source-root . --config .pt/operator.json --output .pt/releases/build --verify-container
```

The helper stamps the actual clean checkout's HEAD into the Docker build, records its tree
and SHA256 of included source bytes, builds for linux/amd64, checks the image's baked commit
environment and revision label, and runs all three existing container smoke tests against
the immutable local image ID. Inherited pytest selection options and automatic plugin
loading cannot weaken this gate; all three expected node IDs must pass exactly once. Source
identity is checked again afterwards. Logs and temporary paths stay beneath `.pt`.

The command writes `containerapp.yaml`, `release.json`, image inspection, JUnit and build/test
logs. With passed local evidence it also writes a guarded `apply.ps1`. Omitting both
verification options renders YAML and a receipt marked `not_requested`, with no apply script.
Output must be a new directory below `.pt`; previous evidence is never overwritten.

The local image ID is a Docker image/config identity. It is not the ACR manifest digest.
The owner publishes the tested immutable image separately and records the resulting registry
reference. Once `.pt/operator.json` contains that reference, finalize without rebuilding:

```powershell
python deploy/prepare_backend_release.py --source-root . --config .pt/operator.json --output .pt/releases/candidate --verified-receipt .pt/releases/build/release.json
```

Retain the previous receipt with its sibling `container-smoke.xml` and `image-inspection.json`.
Reuse verifies the actual JUnit node IDs, image identity and commit stamp, checks recorded
artifact hashes when available, and copies the evidence. `source` records the current clean
preparer checkout; `container_verification.tested_source` and `tested_commit` continue to name
the checkout used for the tested image. This separation also permits a truthful rollback.
These local receipts are operator-retained evidence, not signed supply-chain attestations.

### Owner preflight and apply

Review the resolved YAML, receipt, image digest, target and origins, then verify association
without contacting Azure:

```powershell
pwsh -NoProfile -File .pt/releases/candidate/apply.ps1 -PreflightOnly
```

Before any Azure command, the script checks receipt/YAML hashes and inspects the exact registry
reference locally. Its image ID must equal the tested ID, its `RepoDigests` must contain that
exact reference, and its architecture, OS, baked commit environment and revision label must
match the tested evidence. Missing local metadata fails; it never silently pulls an image.
After this passes, the owner applies the reviewed target using:

```powershell
pwsh -NoProfile -File .pt/releases/candidate/apply.ps1
```

Apply repeats those checks before `az containerapp create` or `update`. Applying creates or
changes paid resources. Azure CLI/provider validation still occurs at that time: local
rendering and local Docker success are not Azure deployment acceptance.

### Cloud acceptance and current platform constraints

`/health` is process health and is used for startup/liveness probes; `/ready` is the separate
operator dependency check. The template uses `Liveness`/`Startup`, targetPort without the
unsupported targetContainerName field, aggregate 1.5 vCPU/3 GiB, min=max one replica and a
180-second graceful termination budget. Startup uses ten attempts at 15-second intervals;
that configuration is not a measured cold-start guarantee.

Keep public ingress disabled until the owner proves the store primitives from both deployed
containers, cross-container visibility, and persistence across replica replacement. A green
local Docker volume test does not prove any of those Azure Files properties. If the real
mount cannot pass, ADR 0005's managed-store-adapter trigger applies. Public ingress is a
separate acceptance action; the helper has no option that pretends to satisfy it.

Microsoft's [Container Apps schema](https://learn.microsoft.com/en-us/azure/templates/microsoft.app/2026-01-01/containerapps)
documents the app identity, ingress and probe fields; the [container sizing reference](https://learn.microsoft.com/en-us/azure/container-apps/containers)
covers aggregate resource pairs. [Managed identity image pull](https://learn.microsoft.com/en-us/azure/container-apps/managed-identity-image-pull)
documents the user-assigned identity path. [NFS mounts](https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts)
require VNet reachability and appropriate ports (445/2049), and Container Apps does not support
NFS encryption in transit. The owner must confirm the account's applicable NFS/secure-transfer
settings rather than disabling security settings by assumption. The [environment storage CLI](https://learn.microsoft.com/en-us/cli/azure/containerapp/env/storage?view=azure-cli-latest)
documents the two named access-mode definitions.

No price is asserted. Before provisioning, price the selected region's two SSD NFS shares,
always-on replica, environment/networking, logging and egress. The [storage scale targets](https://learn.microsoft.com/en-us/azure/storage/files/storage-files-scale-targets)
distinguish a 100 GiB provisioned-v1 floor from a 32 GiB provisioned-v2 floor; do not treat
100 GiB as a universal minimum. Infrastructure availability and cloud filesystem behavior
remain operator prerequisites and acceptance work.

## Publishing what ops owns

The ops process does not move. Captures, decisions, settles and site builds stay on the
machine that owns the ledger; this is only how the bytes reach the backend's read-only mount.

**Order matters, and getting it wrong takes the whole backend down.** The context is the most
recent **live** capture — the newest `fpl-live-` snapshot directory holding `metadata.json`.
Its season/gameweek handoff must name that exact capture before it can be projected. The
resolver does not search older captures for a valid pair. Captures from the other collectors
are ignored here, so a root holding only those
reads as not ready and logs `advice_context_absent` naming the source it wanted. A capture
published without its handoff is therefore not a partial upgrade: it is the newest capture,
it has no projection anyone can name, `capture_context` goes false, and **every** advice route
answers 503 until the handoff lands.

The recipe below is for a new gameweek whose handoff does not already exist on the mount.
It preserves the previous capture and its matching handoff. Publish in this order:

1. **Site data** — `<inputs>/site/data`. Independent of the pair below, but
   `league/members.json` is what makes the league connected at all.
2. **The handoff** — `<inputs>/handoffs/<season>-gw<NN>.json`. Before the capture it belongs
   to, so it is already there the moment the capture becomes visible.
3. **The capture** — `<inputs>/snapshots/<snapshot_id>/`: the payloads first, then
   `metadata.json` last, written to a temporary name in the same directory and renamed into
   place. Only `metadata.json` makes the directory count as a capture, and a same-directory
   rename is the only atomicity a shared filesystem offers. A capture whose payloads are
   present but truncated fails its checksums and takes the backend unready just as surely as a
   missing handoff, so verify the copy before the rename.

No redeploy is involved: publishing a new pair moves the backend to the new week, and the
context is re-resolved on every request rather than cached for the life of the process.

**Recovering from a half-published new gameweek** is the reverse of step 3: withdraw the new
capture's `metadata.json`. The previous capture becomes newest again and remains usable
because this recipe kept its matching handoff. No restart is needed. Capture identity remains
part of every cache key, so old answers keep their original identity.

**Replacing a capture within the same gameweek is outside this recipe.** Handoffs are named
by season/gameweek, and replacing that file overwrites the previous capture's handoff.
Preserve the previous matching handoff before such an update. Rolling it back requires both
withdrawing the new capture marker and restoring the previous matching handoff; withdrawing
the marker alone is insufficient. Readiness can be false while the selected capture and the
handoff refer to different snapshots. Do not treat the pair as an atomic publication.

### Concrete publication transport

Use an existing operator-owned Linux host inside the VNet with the inputs share mounted
ReadWrite at `/mnt/squadopt-inputs`; the application's mount remains ReadOnly. That host must
have OpenSSH, rsync, sha256sum and an authorized writer account. Windows-native AzCopy cannot
upload local files to NFS; Microsoft's [AzCopy NFS limits](https://learn.microsoft.com/en-us/azure/storage/common/storage-use-azcopy-files)
require Linux for local NFS upload/download. Provisioning the Linux host, mounts and SSH
access is a prerequisite, not an action of this helper.

On the Windows ops machine, set these paths to the actual published site, handoff and complete
live snapshot. Use a fresh staging directory per publication; it is outside the mounted tree.

```powershell
$PublishHost = 'publisher@linux-host-in-vnet'
$SiteData = 'C:/ops/squadopt/web/public/data'
$Handoff = 'C:/ops/squadopt/data/handoffs/2026-27-gw04.json'
$Snapshot = 'C:/ops/squadopt/data/snapshots/fpl-live-20260909T060000Z'
ssh $PublishHost 'mkdir -p ~/squadopt-stage/release-gw04'
scp -r $SiteData "${PublishHost}:squadopt-stage/release-gw04/site-data"
scp $Handoff "${PublishHost}:squadopt-stage/release-gw04/handoff.json"
scp -r $Snapshot "${PublishHost}:squadopt-stage/release-gw04/snapshot"
```

On the Linux preparation host, use the matching names below. Refuse an existing snapshot
directory or target gameweek handoff before any publication writes, copy/check payloads,
and expose metadata only as the final rename:

```bash
set -euo pipefail
STAGE="$HOME/squadopt-stage/release-gw04"
INPUTS=/mnt/squadopt-inputs
SNAPSHOT_ID=fpl-live-20260909T060000Z
HANDOFF_NAME=2026-27-gw04.json
test -f "$STAGE/snapshot/metadata.json"
test -f "$STAGE/handoff.json"
test ! -e "$INPUTS/snapshots/$SNAPSHOT_ID"
test ! -e "$INPUTS/handoffs/$HANDOFF_NAME"
mkdir -p "$INPUTS/site/data" "$INPUTS/handoffs" "$INPUTS/snapshots"
rsync -a "$STAGE/site-data/" "$INPUTS/site/data/"
cp "$STAGE/handoff.json" "$INPUTS/handoffs/$HANDOFF_NAME.pending"
cmp "$STAGE/handoff.json" "$INPUTS/handoffs/$HANDOFF_NAME.pending"
mv "$INPUTS/handoffs/$HANDOFF_NAME.pending" "$INPUTS/handoffs/$HANDOFF_NAME"
mkdir "$INPUTS/snapshots/$SNAPSHOT_ID"
rsync -a --exclude=/metadata.json "$STAGE/snapshot/" "$INPUTS/snapshots/$SNAPSHOT_ID/"
(cd "$STAGE/snapshot"; find . -type f ! -path ./metadata.json -print0 | sort -z | xargs -0 sha256sum) > "$STAGE/payloads.sha256"
(cd "$INPUTS/snapshots/$SNAPSHOT_ID"; sha256sum -c "$STAGE/payloads.sha256")
cp "$STAGE/snapshot/metadata.json" "$INPUTS/snapshots/$SNAPSHOT_ID/metadata.json.pending"
cmp "$STAGE/snapshot/metadata.json" "$INPUTS/snapshots/$SNAPSHOT_ID/metadata.json.pending"
mv "$INPUTS/snapshots/$SNAPSHOT_ID/metadata.json.pending" "$INPUTS/snapshots/$SNAPSHOT_ID/metadata.json"
```

Source names above are examples, not evidence of an available GW4 capture. The handoff's
season/gameweek and snapshot identity must agree with the actual ops output. After publication,
check `/ready` and one connected member request through the internal endpoint. If readiness
regresses after this new-gameweek recipe, withdraw the new capture marker on that same host:

```bash
mv "$INPUTS/snapshots/$SNAPSHOT_ID/metadata.json" "$INPUTS/snapshots/$SNAPSHOT_ID/metadata.json.withdrawn"
```

This preserves the marker for diagnosis and selects the previous capture, whose matching
handoff this recipe retained. Do not withdraw that previous capture or handoff. For a same-week
replacement, also restore its previous handoff as described above.

## Rollback

ADR 0006's own: unset `VITE_ADVICE_API_ORIGIN` in the site build, or let the backend die. The
site is the static site again, exactly as before. The backend container can be deleted whole —
it owns no data the ledger needs: the cache recomputes, and pending jobs are recomputable
requests by construction.

Rolling back the *image* reuses the prior verified image's evidence. Keep its receipt, JUnit,
inspection and resolved YAML. Set `.pt/rollback.json` to the intended target, `operation:
"update"`, and the previously deployed immutable registry reference. Then prepare and apply:

```powershell
python deploy/prepare_backend_release.py --source-root . --config .pt/rollback.json --output .pt/releases/rollback --verified-receipt .pt/releases/previous/release.json
pwsh -NoProfile -File .pt/releases/rollback/apply.ps1 -PreflightOnly
pwsh -NoProfile -File .pt/releases/rollback/apply.ps1
```

The prior registry reference must still exist in local Docker metadata and bind to the prior
tested image. Do not rebuild the current HEAD and assign its commit to the older digest.
The new receipt keeps the prior tested commit separate from the preparer checkout. One
resolved YAML moves both containers together. Answers computed by the older code stay
addressable because `repository_commit` is part of the cache key; rollback does not read the
newer code's entries or overwrite them.

Image and data roll back independently. A bad image uses the command above; a bad data release
must restore the previous capture and its matching handoff as described under
[publishing](#publishing-what-ops-owns). Neither requires changing the other release.

## When a member sees no answer

| Symptom | Where to look |
| --- | --- |
| advice routes return 503 | `/ready` and the coded response — inspect the failing store/context check |
| POST returns `404 LEAGUE_NOT_CONNECTED` | the requested league is absent from the published membership tree; `league_tree` may be false |
| jobs queue but never finish | is a worker process running, and is it mounting the same `SQUADOPT_BACKEND_STORE_ROOT`? A worker that exited 1 at startup could not reach the store |
| POST answers `503 NOT_READY` | the store probe is failing; `/ready` names the check, and a missing volume shows up as `cache_store` |
| job `failed` with `CONTEXT_UNAVAILABLE` | the capture moved on between accepting and computing; asking again is the fix |
| job `failed` with `REQUEST_UNREADABLE` | the spec beside the job's key is missing — the store lost a write, so check the probe |
| job `failed` with `TOO_MANY_ATTEMPTS` | a job that cannot finish; read the worker log rather than raising the limit |
| job `failed` with `DETERMINISM_DEFECT` | two different answers under one complete key. This is a real bug in the compute path, never a retry |
