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
resources**. It has not been applied: no Azure resource exists, and every Azure claim below is
a parameter awaiting confirmation rather than a measured fact.

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

# Captures, and the projection handoffs that go with them. The most recent capture that has a
# handoff is the context; publishing a new pair moves the backend to the new week with no
# redeploy.
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

An unready backend answers advice routes with a coded 503. It does not present an empty cache as
a computed absence.

## A local two-process run

Genuinely two processes against one store — this is how to see the whole path work without
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

On Azure this is the same `mkdir` and `chown`, and where it runs from depends on one thing
nobody here could check: whether the NFS share's root is writable by the mounted identity. If
it is, `az containerapp exec` into the api container does it and **no extra resource exists at
all**. If it is not, it takes a one-off root mount of the share from inside the VNet — a
short-lived container instance or a jumpbox — deleted afterwards, and that in turn needs the
share's root-squash setting to permit root. Container Apps cannot express the step itself: an
init container carries the image's own `USER`, and the container spec has no way to override
it. Confirm the share's default root mode before choosing, and record which route was taken.

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
# ... the prepare step above ...
docker run -d --name squadopt-api --publish 127.0.0.1:8000:8000 \
  --volume squadopt-store:/mnt/squadopt-store \
  --volume "$PWD/.local/inputs:/mnt/squadopt-inputs:ro" \
  --env SQUADOPT_BACKEND_STORE_ROOT=/mnt/squadopt-store/store \
  --env SQUADOPT_BACKEND_SITE_DATA_ROOT=/mnt/squadopt-inputs/site/data \
  --env SQUADOPT_BACKEND_SNAPSHOT_ROOT=/mnt/squadopt-inputs/snapshots \
  --env SQUADOPT_BACKEND_HANDOFF_ROOT=/mnt/squadopt-inputs/handoffs \
  squadopt-backend
docker run -d --name squadopt-worker ...same volumes and environment... \
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

## Azure Container Apps

ADR 0006's topology, as [`deploy/containerapp.yaml`](../deploy/containerapp.yaml): one
replica, two containers from the same image digest, only the api with ingress, both mounting
the shared store. **Applying it creates paid resources** (see the note at the top of this
file); nothing below has been applied.

The two mounts of [Configuration](#configuration) are two shares, because they differ in
access mode: `squadopt-store` ReadWrite and `squadopt-inputs` ReadOnly. Both are
environment-level storage entries and are created before the app — one
`az containerapp env storage set` each, and the YAML's header carries both commands.

| Resource | Parameter | Why it is this and not simpler |
| --- | --- | --- |
| subscription / resource group / region | `<SUBSCRIPTION_ID>` `<RESOURCE_GROUP>` `<REGION>` | region decides both latency and price |
| image registry + pull identity | `<REGISTRY_LOGIN_SERVER>` | CI never pushes and holds no cloud credential; whoever pushes records the digest |
| Container Apps environment, VNet-integrated | `<CONTAINER_APPS_ENVIRONMENT>` `<VNET>` `<SUBNET>` | an NFS mount requires a custom VNet |
| storage account, premium `FileStorage` | `<STORAGE_ACCOUNT>` | NFS shares need the premium file tier |
| share `squadopt-store` (ReadWrite) | 100 GiB floor | the queue, the cache and the specs |
| share `squadopt-inputs` (ReadOnly) | 100 GiB floor | snapshots, handoffs, site data |
| NSG rules on the subnet | ports 445 and 2049 | NFS and its mount traffic |
| Log Analytics workspace | `<WORKSPACE>` | the advice events are the only log that matters |
| allowed frontend origins | `<PAGES_ORIGIN>` | `SQUADOPT_BACKEND_ALLOWED_ORIGINS`; a wildcard is refused at startup |

**Every row above is unconfirmed against current Azure documentation.** The environment this
was written in cannot reach `learn.microsoft.com`, so the requirements were assembled from
secondary sources: that an NFS mount needs a custom VNet, that the account must be premium
`FileStorage`, that Container Apps does not support encryption in transit for NFS (so the
account's secure-transfer requirement must be off), that ports 445 and 2049 must be open on
the subnet's NSG, and that a premium share has a 100 GiB provisioned floor. Confirm each
against the official documentation before spending, and correct this table and the YAML in the
same change. The YAML marks the individual fields it could not confirm — the
`terminationGracePeriodSeconds` field and the allowed cpu/memory pairs among them.

**Cost is parameterised on purpose.** The Azure retail pricing API is also unreachable from
here, so no monthly figure is asserted. The standing charges to price are: the two premium
shares at their provisioned floor (this is a floor, not usage — it is billed whether the store
holds anything or not), the replica's compute at `minReplicas: 1` for every hour of the month
(scale-to-zero is deliberately off, because it would stop the worker with a queue behind it),
the environment's own base charge, log ingestion and retention, and egress. Price them for
`<REGION>` and the sizes in the YAML before the first apply.

**Readiness is not the platform's probe.** The YAML probes `/health`, which touches no
dependency. `/ready` is data-dependent by design — false until ops has published a capture,
its handoff and the league tree — so wiring it as the platform's probe would keep a correctly
deployed revision from ever going healthy, and with one replica the platform's own 503 would
hide which of the three checks failed. `/ready` stays the operator's own `curl`.

**Bootstrap order.** [Preparing the shared mount](#preparing-the-shared-mount) is the same
`mkdir` and `chown` here as locally, and it runs **before** the first revision that contains
the worker: the worker exits non-zero when it cannot reach the store, and a container that
keeps exiting recycles the replica — which can leave no way in to create the directory.

## Publishing what ops owns

The ops process does not move. Captures, decisions, settles and site builds stay on the
machine that owns the ledger; this is only how the bytes reach the backend's read-only mount.

**Order matters, and getting it wrong takes the whole backend down.** The context is the most
recent **live** capture that has a handoff — the newest `fpl-live-` snapshot directory holding
`metadata.json`, projected through the handoff addressed by *that capture's* season and
gameweek. Captures from the other collectors are ignored here, so a root holding only those
reads as not ready and logs `advice_context_absent` naming the source it wanted. A capture
published without its handoff is therefore not a partial upgrade: it is the newest capture,
it has no projection anyone can name, `capture_context` goes false, and **every** advice route
answers 503 until the handoff lands.

So publish in this order, always:

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

**Recovering from a half-published week** is the reverse of step 3: delete the new capture's
`metadata.json`. The backend falls back to the previous capture — which still has its handoff —
on the next request, with no restart. Nothing wrong is served in the meantime, because the
capture id is part of every cache key: answers computed under the older capture are addressed
under the older capture, and the rolled-back week's entries stay addressable if it is
republished.

This transport is deliberately not scripted yet. How the bytes cross from a Windows ops
machine to an Azure Files NFS share — `azcopy`, an SMB sibling share, a jumpbox inside the
VNet — is exactly what could not be confirmed from here, and a helper encoding a guess would
be worse than four commands whose order is written down. Script it once the transport is
decided.

## Rollback

ADR 0006's own: unset `VITE_ADVICE_API_ORIGIN` in the site build, or let the backend die. The
site is the static site again, exactly as before. The backend container can be deleted whole —
it owns no data the ledger needs: the cache recomputes, and pending jobs are recomputable
requests by construction.

Rolling back the *image* is a re-apply of the previous digest: put it back in
`deploy/containerapp.yaml` and apply the same file.

```bash
az containerapp update --resource-group <RESOURCE_GROUP> --name squadopt-backend \
  --yaml deploy/containerapp.yaml
```

One file, so both containers move together — two containers on different commits would answer
at two different cache keys. (`az containerapp update --image` is shorter, but which of the two
containers it means is UNVERIFIED here; the file is unambiguous.) Answers computed by the older
code stay addressable because `repository_commit` is part of the cache key: the rollback does
not read the newer code's entries and does not overwrite them.

Image and data roll back independently, and that is why they are kept separate: a bad image is
the command above, a bad data release is the `metadata.json` deletion under
[publishing](#publishing-what-ops-owns). Neither needs the other.

## When a member sees no answer

| Symptom | Where to look |
| --- | --- |
| every advice route 503 | `/ready` — one of the three checks is false, and it names which |
| jobs queue but never finish | is a worker process running, and is it mounting the same `SQUADOPT_BACKEND_STORE_ROOT`? A worker that exited 1 at startup could not reach the store |
| POST answers `503 NOT_READY` | the store probe is failing; `/ready` names the check, and a missing volume shows up as `cache_store` |
| job `failed` with `CONTEXT_UNAVAILABLE` | the capture moved on between accepting and computing; asking again is the fix |
| job `failed` with `REQUEST_UNREADABLE` | the spec beside the job's key is missing — the store lost a write, so check the probe |
| job `failed` with `TOO_MANY_ATTEMPTS` | a job that cannot finish; read the worker log rather than raising the limit |
| job `failed` with `DETERMINISM_DEFECT` | two different answers under one complete key. This is a real bug in the compute path, never a retry |
