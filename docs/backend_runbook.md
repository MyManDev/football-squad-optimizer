# Advice backend runbook

The static site's runbook is [deployment_runbook.md](deployment_runbook.md); this is the other
deploy surface. They fail independently on purpose: with the backend down or absent the site is
the static site, byte for byte ([ADR 0006](architecture/decisions/0006-backend-hosting.md)).

**Nothing here is a deployment.** No paid resource is created by reading it, and the API is not
exposed to the internet by running it locally. The hosting decision — Azure Container Apps, one
replica, two containers, a durable Azure Files NFS share — is recorded in ADR 0006 and is not
re-decided here.

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

```bash
# The one shared ReadWrite mount. jobs/, cache/, specs/ and probe/ are derived from it, so
# the api and the worker cannot be pointed at two stores that agree about nothing. It must
# already exist: the backend never creates it, because a process that creates its own store
# has quietly accepted a directory nobody mounted.
SQUADOPT_BACKEND_STORE_ROOT=/mnt/squadopt-store

# What ops publishes. The read side answers "is this league connected" from this tree and
# never from an upstream call.
SQUADOPT_BACKEND_SITE_DATA_ROOT=/mnt/squadopt-site/data

# Captures, and the projection handoffs that go with them. The most recent capture that has a
# handoff is the context; publishing a new pair moves the backend to the new week with no
# redeploy.
SQUADOPT_BACKEND_SNAPSHOT_ROOT=/mnt/squadopt-ops/snapshots
SQUADOPT_BACKEND_HANDOFF_ROOT=/mnt/squadopt-ops/handoffs

# An allowlist, never a wildcard (ADR 0006). Empty means no cross-origin access at all.
SQUADOPT_BACKEND_ALLOWED_ORIGINS=https://squadopt.pages.dev

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

A pass is held for thirty seconds, not for ever. A store can stop working after it started, and
a gate that cached its first success would keep reporting a mount that has since gone away. A
failure is never cached, so a mount that arrives late brings the service up without a restart.

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
| `cache_store` | the store probe has not passed on this path — a root that does not exist counts, and that is what a forgotten volume looks like |

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

## Rollback

ADR 0006's own: unset `VITE_ADVICE_API_ORIGIN` in the site build, or let the backend die. The
site is the static site again, exactly as before. The backend container can be deleted whole —
it owns no data the ledger needs: the cache recomputes, and pending jobs are recomputable
requests by construction.

Rolling back the *image* is the ordinary redeploy of the previous tag. Answers computed by the
older code stay addressable because `repository_commit` is part of the cache key: the rollback
does not read the newer code's entries and does not overwrite them.

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
