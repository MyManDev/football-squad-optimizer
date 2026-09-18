# Hosting the advice backend for nothing

The advice backend is built and tested and runs nowhere
([backend runbook](backend_runbook.md), [ADR 0006](architecture/decisions/0006-backend-hosting.md)).
ADR 0006 chose Azure Container Apps with an Azure Files NFS share, and applying that creates
paid resources. This document is the zero-cost route: what can carry the same two processes
for no money, what each option costs in other ways, and the exact steps for the one that
works tomorrow.

It does not re-decide ADR 0006. Running the backend on the owner's PC keeps every rule that
ADR set (one shared ReadWrite filesystem that every process mounts, only the api reachable,
an origin allowlist, the static site as the fallback) and changes only who supplies the
machine. If the PC route becomes the standing deployment, that belongs in ADR 0006's status
history.

Provider facts below were read from the providers' own pages on **2026-09-17**. Each carries
its URL. Where a fact could not be confirmed on an official page it is marked UNVERIFIED and
nothing is built on it.

## What the backend needs

| Need | Why |
| --- | --- |
| x86-64 Windows or Linux, Python 3.12 or newer | `constraints.txt` pins `numpy==2.5.2` and `scipy==1.18.0`, which need 3.12; ADR 0006 admits aarch64 only after its solver parity is measured |
| `ortools==9.15.6755` wheels | CP-SAT is the solver; there is no pure-Python fallback |
| one core per concurrent solve | `configure_solver` sets `num_search_workers = 1`, and a worker runs one job at a time |
| a long-running worker process | the worker polls the queue; nothing starts it per request |
| one persistent file store shared by api and workers | the queue, the cache and the job specs are files; the adapters need `O_EXCL` create, `os.link` create-once and mtime as a heartbeat (ADR 0006) |
| read access to captures, handoffs and the published tree | the backend answers from what ops publishes and never calls upstream |
| inbound HTTPS on a hostname the site can call | the browser posts to it cross-origin |

## Measured on the owner's PC, 2026-09-17

One api and **one** worker, started by `scripts/run_backend_local.ps1` from this branch's
code, reading the main checkout's `data/snapshots`, `data/handoffs` and `web/public/data`
and writing a scratch store outside the checkout. Requests by `scripts/smoke_backend_local.py`
for league 352490, entry 5662073, capture `fpl-live-20260917T103311Z-d0bb92785d5c`
(2026-27 gameweek 5). The machine was also running a 15-process league build at the time,
so these are timings under load, not best cases.

| Request | POST to completed | Worker `wall_seconds` | Solver status |
| --- | --- | --- | --- |
| saf-puan, window 1, first request (the worker projects the capture first) | 8.1 s | 5.353 | OPTIMAL |
| saf-puan, window 1, another member (entry 2199732), context already loaded | 6.1 s | 3.784 | OPTIMAL |
| the same request again | answered 200 from the cache, no job | not applicable | OPTIMAL |
| saf-puan, window 3 | 95.2 s | 92.986 | FEASIBLE |
| saf-puan, window 5 | 209.8 s | 208.464 | FEASIBLE |
| ortak-koru, window 1, rival 2199732 | 20.3 s | 18.555 | OPTIMAL |
| fark-yarat, window 1, rival 2199732 | 22.4 s | 20.620 | OPTIMAL |

The first column includes up to 2 s of the worker's idle wait and up to 2 s of the smoke's
poll interval, which is why it exceeds the worker's own figure.

Other things the run showed:

- The worker logged `advice_worker_started` 4 s after launch, and `/ready` answered
  `{"capture_context": true, "league_tree": true, "cache_store": true}` with no preparation
  beyond creating the store directory. The store probe passes on the PC's NTFS disk. That is
  evidence about this disk and nothing else.
- A request carrying `X-Forwarded-For: 6.6.6.6, 203.0.113.9` from loopback was logged by
  uvicorn as client `203.0.113.9`. The rate limiter's address bucket is therefore the entry
  Cloudflare appends, and a value the visitor sends is ignored. See
  [The client address](#the-client-address).
- `-Stop` ended four processes for one api and one worker. `.venv\Scripts\python.exe` is a
  launcher whose child is the interpreter; the script stops both. After it, no process
  matched, the port had no listener and the pid file was gone.
- Memory per process was not measured.

What the numbers mean for tomorrow: a window-5 request holds a worker for about three and a
half minutes, and the site gives up on a job after 300 s (`useAdviceJob.ts`, 150 polls at
2 s). With one worker a second member who asks during that time waits behind it and can run
out of patience before their job starts. Start several workers. Each busy worker is one
core and the PC has 32 logical CPUs, so `-Workers 6` leaves the weekly run its 15.

## Tomorrow: the PC and a Cloudflare Tunnel

### 1. Start the backend

```powershell
powershell -ExecutionPolicy Bypass -File scripts\run_backend_local.ps1 -Workers 6
```

The script starts `uvicorn --factory squadopt.api.runtime:build_app` on `127.0.0.1:8000`
and N `python -m squadopt.platform.advice_worker` processes from `.venv`, with:

| Variable | Value |
| --- | --- |
| `SQUADOPT_BACKEND_STORE_ROOT` | `data\runtime\backend` (`data/runtime/` is git-ignored) |
| `SQUADOPT_BACKEND_SITE_DATA_ROOT` | `web\public\data` |
| `SQUADOPT_BACKEND_SNAPSHOT_ROOT` | `data\snapshots` |
| `SQUADOPT_BACKEND_HANDOFF_ROOT` | `data\handoffs` |
| `SQUADOPT_BACKEND_ALLOWED_ORIGINS` | `SITE_ORIGINS` from `platform/backend_runtime.py`; a test holds the two together |
| `SQUADOPT_BACKEND_RATE_LIMIT`, `..._RATE_WINDOW_SECONDS` | 30 per 60 s, the code's defaults, settable with `-RateLimit` and `-RateWindowSeconds` |
| `SQUADOPT_REPOSITORY_COMMIT` | `git rev-parse HEAD`, stamped once so the api and every worker file answers under one identity |
| `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS` | 1 |
| `SQUADOPT_BACKEND_ARTIFACT_ROOT`, `SQUADOPT_BACKEND_CLUB_NEWS_SOURCE` | `<repo>/artifacts` and the committed example fixture; the inputs of the Top 100 setting and the manager's word (`-ArtifactRoot`, `-ClubNewsSource` override) |

It writes `data\runtime\backend\run\backend.pids.json`, logs to
`data\runtime\backend\logs\<role>-<utc stamp>.out.log` and `.err.log` (a new pair per start,
never overwritten), refuses to start while a recorded process is alive, and `-Stop` stops
exactly the recorded processes and their interpreter children. A recorded pid is only
touched when the live process has the recorded start time. `-Status` prints the processes,
`/ready` and the queue depth.

Threads: CP-SAT runs one search worker per solve and a worker computes one job at a time,
so N workers are at most N busy cores. The three BLAS variables pin numpy's and scipy's
pools to one thread so N workers cannot oversubscribe through them. Whether the projection
uses a threaded BLAS call at all was not measured.

Three things to know before relying on it:

- **Stopping is a kill.** Windows delivers no SIGTERM, so a worker stopped in the middle of
  a job leaves it `running`. The next worker walks it back to `queued` once the claim is
  older than the 300 s lease and computes it again. Stop when `-Status` shows
  `advice_queue_depth 0`.
- **The processes end at logoff, sleep or reboot** and nothing restarts them. A scheduled
  task "at log on" that runs the script makes that automatic. The PC must not sleep while
  members are expected; that is a Windows power setting for the owner to change.
- **The answer's identity includes the commit.** After a `git pull` and a restart the cache
  starts empty for the new commit. Old entries stay on disk and stay addressable.

Then prove it locally:

```powershell
.venv\Scripts\python.exe -m scripts.smoke_backend_local --base-url http://127.0.0.1:8000 --league 352490 --entry 5662073
```

### What `/ready` needs on this machine

All three checks come from files, re-read on every request, so none of them needs a restart.

| Check | Holds when | Code |
| --- | --- | --- |
| `capture_context` | the lexically newest `fpl-live-*` directory under `data\snapshots` has a `metadata.json`, **and** `data\handoffs\<season>-gw<NN>.json` exists for that capture's own season and gameweek, **and** that handoff's `source_snapshot_id` is that capture | `capture_context.py`, `load_capture_identity` |
| `league_tree` | `web\public\data\league\members.json` is readable | `advice_read.py`, `FileLeagueDirectory.readable` |
| `cache_store` | the store root exists and passes the probe | `store_probe.py` |

Two consequences:

- Between the weekly run writing a new capture and writing its handoff, `capture_context` is
  false and advice routes answer 503. Today that gap was about seven minutes (capture id
  stamped 10:33Z, handoff written 10:40Z). The site treats a 5xx as "backend down" and
  serves the published static answer, so members see the static site for those minutes.
  A handoff built from an older capture of the same gameweek does not count: the capture
  named inside it must be the newest one.
- Nothing checks that `members.json` names the same season and gameweek as the capture.
  `league_tree` only asks whether the file can be read. If the published tree is a week
  behind the newest capture, the page shows one week and the button computes another.
  Publish the week before relying on the button.

### 2. The tunnel

`cloudflared` makes an outbound connection from the PC to Cloudflare. No port is opened on
the router and the PC gets no public address. Tunnel itself is free
(<https://blog.cloudflare.com/tunnel-for-everyone/>); the documented limits are counts of
tunnels and routes, not traffic
(<https://developers.cloudflare.com/cloudflare-one/account-limits/>). A locally managed
tunnel, the kind configured by a file, is still documented; Cloudflare recommends the
dashboard-managed kind for most uses
(<https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/>).

**The hostname is `squadopt-api.mymandev.com`, not `api.squadopt.mymandev.com`.** Universal
SSL on the Free plan covers the zone and its first-level names only; a deeper name is served
without a valid certificate unless Advanced Certificate Manager is bought
(<https://developers.cloudflare.com/ssl/edge-certificates/universal-ssl/limitations/>).

What only the owner can do, in a browser: install `cloudflared`, and approve
`cloudflared tunnel login`, which opens Cloudflare's authorisation page for the
`mymandev.com` zone. Whether Cloudflare asks for a payment method at that point was not
confirmed: the Zero Trust onboarding page says the Free plan still asks for one and does
not charge it (<https://developers.cloudflare.com/cloudflare-one/setup/>), and no page says
whether the command-line login goes through that onboarding. UNVERIFIED either way.

```powershell
winget install --id Cloudflare.cloudflared
cloudflared tunnel login
cloudflared tunnel create squadopt-api
cloudflared tunnel route dns squadopt-api squadopt-api.mymandev.com
```

`login` writes `cert.pem` and `create` writes `<TUNNEL-UUID>.json` into
`%USERPROFILE%\.cloudflared`
(<https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/local-tunnel-terms/>).
The JSON file is the tunnel's credential. It stays out of Git.

Copy [`deploy/cloudflared/config.example.yml`](../deploy/cloudflared/config.example.yml) to
`%USERPROFILE%\.cloudflared\config.yml`, fill in the UUID and the user name, then:

```powershell
cloudflared tunnel ingress validate
cloudflared tunnel ingress rule https://squadopt-api.mymandev.com/metrics
cloudflared tunnel ingress rule https://squadopt-api.mymandev.com/ready
cloudflared tunnel run squadopt-api
```

The second command must report the `http_status:404` rule and the third the
`http://127.0.0.1:8000` rule. Rules are tried top to bottom, `path` is a Go regular
expression, and the last rule must match everything
(<https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/configuration-file/>).
That page shows `http_status` only on the final rule; using it on an earlier rule follows
from the documented ordering and is what the second command checks.

Then the same smoke through the public name, with the browser's half of the question:

```powershell
.venv\Scripts\python.exe -m scripts.smoke_backend_local --base-url https://squadopt-api.mymandev.com --league 352490 --entry 5662073 --origin https://squadopt.mymandev.com
```

and `curl.exe -i https://squadopt-api.mymandev.com/metrics` must answer 404.

**As a Windows service**, so the tunnel survives a logoff
(<https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/windows/>).
From an elevated prompt:

1. `cloudflared.exe service install`
2. Create `C:\Windows\System32\config\systemprofile\.cloudflared` and copy `config.yml`,
   `cert.pem` and `<TUNNEL-UUID>.json` into it. Change `credentials-file` in that copy to
   the new location.
3. In the registry key `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Services\Cloudflared`
   set `ImagePath` to
   `C:\Cloudflared\bin\cloudflared.exe --config=C:\Windows\System32\config\systemprofile\.cloudflared\config.yml tunnel run`
   with the path `cloudflared.exe` really has on this machine.
4. `sc start cloudflared`; after any change to the config, `sc stop cloudflared` then
   `sc start cloudflared`.

The service keeps the tunnel up, not the backend. With the tunnel up and the backend down,
Cloudflare answers 502 and the site serves the static tree.

### Security posture

- **Only the api is reachable.** The api binds `127.0.0.1`. The tunnel's one forwarding rule
  names that port. Workers open no listener unless `-WorkerMetricsBasePort` is given, that
  listener binds `127.0.0.1` too, and its port is never written into the tunnel config.
- **`/metrics` is refused at the tunnel.** Every scrape lists the whole job store under the
  queue lock, so a stranger polling it slows every member's request. The ingress rule
  answers 404 for `/metrics`, `/docs`, `/redoc` and `/openapi.json` before anything reaches
  the PC. `-Status` reads `/metrics` locally.
- **A WAF rule as the second lock**, in case the config file is ever replaced by one without
  the path rule. Free zones get 5 custom rules, with Block available and `http.host` and
  `starts_with` unrestricted (<https://developers.cloudflare.com/waf/custom-rules/>,
  <https://developers.cloudflare.com/ruleset-engine/rules-language/functions/>).
  Security, WAF, Custom rules, Create rule, action **Block**, expression:

  ```text
  (http.host eq "squadopt-api.mymandev.com" and not starts_with(http.request.uri.path, "/api/v1/") and http.request.uri.path ne "/health" and http.request.uri.path ne "/ready")
  ```

  It allows what a browser and an operator need and blocks the rest, `/metrics` included.
- **A rate limiting rule.** The Free plan allows exactly one, and it is narrow: the
  expression may use only Path and Verified Bot, requests are counted per IP, the period is
  10 s and the mitigation lasts 10 s
  (<https://developers.cloudflare.com/waf/rate-limiting-rules/>). Host is not available,
  so the rule is written on the path, and no other hostname in the zone serves `/api/v1/`.
  Security, WAF, Rate limiting rules:

  ```text
  expression:       (starts_with(http.request.uri.path, "/api/v1/"))
  characteristics:  IP
  requests:         50
  period:           10 seconds
  action:           Block, for 10 seconds
  ```

  Why 50: one open member page polls a job once per 2 s, 5 requests per 10 s, plus the
  POST and its preflight. Turkish mobile networks put many subscribers behind one address,
  so the threshold has to leave room for several members on one IP. It is a lid on
  hammering, not a quota. That Block is the only action a Free rule may take was not
  confirmed on the page; it is the action to choose.
- **The application's own limit is the one that protects the solver.** 30 POSTs per 60 s per
  client address and per (capture, entry), applied before the cache read; at most one open
  job per distinct request; a computed answer is served from the cache for ever after.
  Polls are not limited by the application, which is what the Cloudflare rule is for.
- **What a Cloudflare block looks like to the site.** Cloudflare's 403 and 429 pages carry
  no CORS headers, so the browser reports a network failure and the client falls back to
  the static tree. A 4xx from the api itself is different: the client treats it as a
  refusal and shows it.
- **No authentication.** Anyone who knows a member's entry id can ask for that member's
  advice. The static site already publishes the same advice for the same ids, so the tunnel
  exposes nothing new; it exposes the PC's CPU, which the limits above bound.
- **Requests are short.** Cloudflare gives an origin 125 s to start answering before a 524
  (<https://developers.cloudflare.com/fundamentals/reference/connection-limits/>). No route
  waits for a solve: the POST files a job and returns, and the page polls.
- The api's access log records visitor addresses in `logs\api-*.out.log`. It is on the
  owner's disk under a git-ignored path.

### The client address

The rate limiter buckets by `request.client.host`. Behind the tunnel the TCP peer is
always `127.0.0.1`, so without forwarded headers every member would share one bucket.
uvicorn 0.52.4 (`uvicorn/middleware/proxy_headers.py`) replaces the client address with one
taken from `X-Forwarded-For` when the peer is in `--forwarded-allow-ips`, walking the list
from the right and taking the first entry that is not itself trusted. Cloudflare appends the
connecting address to any `X-Forwarded-For` the visitor sent
(<https://developers.cloudflare.com/fundamentals/reference/http-headers/>), so the rightmost
entry is Cloudflare's and the visitor cannot choose their bucket. The script passes
`--proxy-headers --forwarded-allow-ips 127.0.0.1`, which are also uvicorn's defaults, and
the tunnel config says `127.0.0.1` rather than `localhost` so the peer is never `::1`.
uvicorn does not read `CF-Connecting-IP`. The local run above confirmed the behaviour.

### 3. Tell the site build where the api is

`createAdviceClient` reads `import.meta.env.VITE_ADVICE_API_ORIGIN`
(`web/src/features/league/advice/adviceClient.ts`). Vite substitutes it **at build time**,
and the production site is not built by the deploy workflow: `deploy-pages.yml` downloads
the `site` artifact that `ci.yml`'s `web` job built and uploaded for the tagged commit on
`main`. So the variable has to be present in **`ci.yml`, job `web`, step `Build`**. Setting
it in `deploy-pages.yml`, in the `cloudflare-pages` environment, or in the Cloudflare Pages
dashboard changes nothing, because none of those builds the bundle.

It is an address, not a secret: it is readable in the shipped JavaScript. Make it a
repository **variable** so it can be changed or emptied without a commit:

```bash
gh variable set ADVICE_API_ORIGIN --repo MyManDev/football-squad-optimizer --body "https://squadopt-api.mymandev.com"
```

The workflow change, applied on its own pull request because workflows are a
release-critical path:

```diff
--- a/.github/workflows/ci.yml
+++ b/.github/workflows/ci.yml
@@ jobs: web: steps:
       - name: Build
+        env:
+          # Unset or empty is the static site, byte for byte (ADR 0006). A repository
+          # variable, not a secret: the value ships in the bundle.
+          VITE_ADVICE_API_ORIGIN: ${{ vars.ADVICE_API_ORIGIN }}
         run: npm run build
```

An unset variable expands to the empty string, and `createAdviceClient` treats empty as no
backend, so the diff is inert until the variable exists.

What follows from building it this way:

- The variable must be set **before** the CI run on `main` that builds the release commit.
  A value changed afterwards reaches production only through a new CI run on `main` and a
  new release tag.
- Pull-request previews get the origin too. Their origin (`pr-N.squadopt.pages.dev`) is not
  in the allowlist, so the browser refuses the answer and the preview serves the static
  tree. That is the intended behaviour for a preview.
- The same `dist` is what CI's Playwright smoke runs against, from `http://127.0.0.1:4173`,
  which the allowlist also refuses, so the smoke exercises the fallback path. A local run on
  2026-09-17 against a bundle built with the origin (the hostname did not resolve yet)
  passed 78 of 81 tests. The three failures were not specific to the origin: the two
  accessibility timeouts passed on a rerun with the same bundle, and the `league-members`
  selection tests failed the same way against a bundle built without it, on a machine that
  was running a 15-process build. That is weak evidence, not a green run. The pull request
  that applies the diff gets the real answer from CI, which is a reason to apply it on a
  pull request and not directly on `main`.
- Rollback is ADR 0006's: delete the variable (`gh variable delete ADVICE_API_ORIGIN`),
  rebuild, release. Or stop the backend; the site falls back on its own.

## The options compared

### (a) The owner's PC and a Cloudflare Tunnel

Free: everything. Runs the current code unchanged, on the machine and operating system the
solver's budgets were measured on, with every input already on its disk, so there is no
transport step for captures and handoffs. Limits: the backend exists while the PC is on,
awake, logged in and connected; a home uplink; one machine shared with the weekly run. Risk:
availability only. With the PC off the site is the static site.

### (b) Oracle Cloud Always Free, Ampere A1

Free: 1,500 OCPU hours and 9,000 GB hours of A1 Flex a month, which Oracle states as 2 OCPUs
and 12 GB; 200 GB of block volume; 10 TB of egress
(<https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm>).
That is half the earlier allowance. The reduction's date was found only in secondary
reporting and is UNVERIFIED here. The two free AMD micro instances are 1/8 OCPU and 1 GB
each, too small for a solve.

Wheels exist: `ortools 9.15.6755` publishes
`manylinux_2_26_aarch64.manylinux_2_28_aarch64` wheels for cp311, cp312 and cp313
(<https://pypi.org/pypi/ortools/9.15.6755/json>), so Ubuntu or Oracle Linux installs it.
The disk is a real block device, so the store's primitives should hold; the probe has not
been run there.

Limits and risk: a credit or debit card is required for identity verification
(<https://www.oracle.com/cloud/free/faq/>). Oracle may reclaim an Always Free instance whose
CPU (95th percentile), network and, on A1, memory use all stay under 20 for seven days; an
idle advice backend is exactly that profile. Creating an A1 instance can fail with "out of
host capacity" for days. **ADR 0006 does not admit aarch64 yet**: the solver's determinism
and time budget were measured on x86-64, and aarch64 becomes eligible when its parity is
measured. Captures, handoffs and the published tree would have to be copied to the instance
in the runbook's order on every publish, which is a transport nobody has scripted. Inbound
HTTPS would still come from a Cloudflare Tunnel, which avoids opening the instance's
firewall.

### (c) Google Cloud Run and Cloud Run jobs

Free per month: 180,000 vCPU-seconds, 360,000 GiB-seconds and 2 million requests for
request-billed services; 240,000 vCPU-seconds and 450,000 GiB-seconds for jobs
(<https://cloud.google.com/run/pricing>). A billing account, so a card, is required
(<https://docs.cloud.google.com/free/docs/free-cloud-features>). 240,000 vCPU-seconds is
about 1,100 window-5 solves at the 208 s measured above, so the compute allowance is not the
problem.

The store is. An instance's filesystem is memory and disappears with the instance
(<https://docs.cloud.google.com/run/docs/container-contract>). The mountable alternative,
Cloud Storage FUSE, has no hard links and no file locking, and renames are not atomic
without a hierarchical-namespace bucket
(<https://docs.cloud.google.com/storage/docs/cloud-storage-fuse/overview>). `os.link`
create-once is how the cache, job submission and the open-job index work, so the file
adapters cannot sit on it. An NFS mount needs a VPC and a file server, which is not free.
With request billing the worker's polling loop gets no CPU between requests; a worker pool
or instance billing keeps it alive and spends the allowance around the clock.

Does the current code run unchanged: no. It needs a queue and cache that are not files,
which is ADR 0005's trigger and is work nobody has done: no managed-store adapter exists in
`src/`. Risk: a card on file with a provider that bills past the allowance.

### (d) GitHub Actions as the worker

Standard runners are free for public repositories and 2,000 minutes a month for private
ones on the Free plan
(<https://docs.github.com/en/billing/concepts/product-billing/github-actions>); a public
repository's `ubuntu-latest` has 4 vCPU and 16 GB
(<https://docs.github.com/en/actions/reference/runners/github-hosted-runners>). A request
would be dispatched by `POST /repos/{owner}/{repo}/actions/workflows/{id}/dispatches` with a
token holding Actions: write (<https://docs.github.com/en/rest/actions/workflows>). That
token cannot live in a browser, so an api front would still be needed to hold it, and the
job would have to fetch the captures, install the pinned stack or restore it from a cache,
solve, and publish the answer somewhere the api can read. Start latency is not documented;
every request would pay a runner start and an environment restore before the first solver
second.

It fits badly, and the terms settle it: the Actions section of GitHub's additional product
terms prohibits using Actions for activity unrelated to producing, testing, deploying or
publishing the repository's software, and names serverless computing as an example of
disproportionate burden
(<https://docs.github.com/en/site-policy/github-terms/github-terms-for-additional-products-and-features>).
A member's button press is that. The weekly scheduled publish is a different matter and is
not what is being asked here. Risk: the repository or the account being disabled.

### (e) Render, Fly.io, Railway, Koyeb

- **Render.** A free web service has 512 MB, spins down after 15 minutes without traffic
  and takes about a minute to return. Free instances have no persistent disk and there are
  no free background workers (<https://render.com/docs/free>). No disk and no worker means
  no fit.
- **Fly.io.** No free allowance for new accounts. The trial ends at 2 VM hours or 7 days
  and a card is needed to continue (<https://fly.io/docs/about/pricing/>,
  <https://fly.io/docs/about/free-trial/>).
- **Railway.** A one-time 5 dollar trial credit, then a Free plan with 1 dollar of usage a
  month and 0.5 GB per service (<https://railway.com/pricing>). That does not keep an api
  and a worker running for a month.
- **Koyeb.** The documented free instance is 0.1 vCPU and 512 MB, web services only, no
  volumes, no worker services (<https://www.koyeb.com/docs/reference/instances>), and a
  card is mandatory (<https://www.koyeb.com/docs/faqs/pricing>). Since joining Mistral AI,
  Koyeb has said the Starter plan is being removed for new users
  (<https://www.koyeb.com/blog/koyeb-is-joining-mistral-ai-to-build-the-future-of-ai-infrastructure>).

ADR 0006 had already ruled out service-private volumes (Render's and Railway's paid ones)
because the api and the worker are two services that must see one store. None of the four
is a zero-cost host for this backend.

### (f) Cloudflare Workers or Pages Functions as the api front only

The solver cannot run there: Python Workers accept pure-Python and Pyodide packages, not
native wheels, and OR-tools is not among them
(<https://developers.cloudflare.com/workers/languages/python/packages/>); the Free plan
allows 10 ms of CPU per request (<https://developers.cloudflare.com/workers/platform/limits/>).
Cloudflare Containers are described only under the paid Workers plan
(<https://developers.cloudflare.com/containers/pricing/>).

As a front it is feasible on free tiers: 100,000 Worker requests a day, Queues now included
on the Free plan with 10,000 operations a day
(<https://developers.cloudflare.com/queues/platform/pricing/>), R2 with 10 GB and 1 million
Class A operations a month (<https://developers.cloudflare.com/r2/pricing/>), D1 with
100,000 rows written a day (<https://developers.cloudflare.com/d1/platform/pricing/>). The
shape would be a Worker that validates, files the request in a Queue or D1 and serves
answers from R2, with the PC's worker pulling jobs outbound and uploading answers. Members
would then get cached answers while the PC is off, and the PC would need no tunnel.

It is not a configuration change. It is a rewrite of the api in another language with a new
queue and cache adapter on the Python side, a second implementation of `backend_api_v1` to
keep in step, and it still computes nothing without a machine running the worker. It could
not live in the Pages project: ADR 0004 and the Pages preflight refuse `_worker.js` and
`functions/`, so it would be a separate Worker on its own route. Risk: two api
implementations drifting.

### Summary

| Option | Free allowance that matters | Hard limit that matters here | Card | Current code unchanged | Main risk |
| --- | --- | --- | --- | --- | --- |
| (a) PC + Cloudflare Tunnel | all of it | up only while the PC is on, awake and logged in | UNVERIFIED for the tunnel login | yes | availability |
| (b) Oracle A1 Always Free | 2 OCPU, 12 GB, 200 GB disk | aarch64 not yet admitted by ADR 0006; idle reclamation; capacity errors; inputs must be copied in | yes | yes, after a parity measurement | instance reclaimed or never created |
| (c) Cloud Run | 180,000 to 240,000 vCPU-seconds a month | no filesystem with hard links; worker loop needs always-on CPU | yes | no, needs non-file queue and cache | billing past the allowance |
| (d) GitHub Actions as worker | unlimited minutes on a public repository | terms prohibit it; runner start on every request; token cannot be in the browser | no | no | account or repository disabled |
| (e) Render / Fly.io / Railway / Koyeb | none that holds an api, a worker and a shared disk | no free disk, no free worker, or no free plan | varies | no | not applicable |
| (f) Cloudflare Worker front + PC worker | 100,000 requests, 10,000 queue operations a day | 10 ms CPU per request; no native wheels; solver still needs a machine | no | no, api rewrite and new adapters | two api implementations |

## Recommendation

**Tomorrow: (a).** Start the backend with the script, run the local smoke, create the
tunnel on `squadopt-api.mymandev.com`, run the smoke through it with `--origin`, add the
two Cloudflare rules, set the repository variable, apply the three-line workflow diff, and
release. Every step but the release can be undone by stopping a process, and with the PC
off the site is what it is today.

**Next: (b), behind the same tunnel hostname, after one measurement.** Oracle's A1 instance
is the only always-on free offer found that gives this backend what it needs without
rewriting it: real cores, a real disk, long-running processes. Before it can carry members
it needs, in this order: the aarch64 parity measurement ADR 0006 asks for (the same
requests solved on both architectures, answers compared); a scripted copy of captures,
handoffs and the published tree in the runbook's publish order; the store probe run on the
instance's disk; and a decision about the reclamation policy, since an idle instance is
the normal state of this service. Moving is then a DNS-level change: point the tunnel at
the instance instead of the PC, and the site's build does not change. If the card
requirement or the capacity lottery rules Oracle out, the fallback is not another free
host. It is (a) kept running, or ADR 0006's paid topology.
