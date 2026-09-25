# ADR 0009: Where the advice backend runs, five options compared for the owner's decision

- **Status:** proposed
- **Date:** 2026-09-25
- **Decider:** Ertuğrul (repository owner). Nothing here is decided until he picks an option.
- **Related:** [ADR 0004](0004-cloudflare-pages-deployment.md),
  [ADR 0005](0005-persistence-boundaries.md), [ADR 0006](0006-backend-hosting.md),
  [backend runbook](../../backend_runbook.md), [free hosting and the tunnel](../../backend_free_hosting.md),
  [advice capacity](../advice_capacity.md). Future-work items R2 ("backend on a remote host
  with shared storage") and I44 ("always-on machine, Oracle") of the 2026-09-25 repository audit.

## Context

The advice backend (one api, six workers) runs on the owner's Windows PC, and the
`squadopt-api` Cloudflare Tunnel connector runs beside it. Every compute button on the member
pages depends on that one machine being on, awake, logged in and online. With the backend
unreachable the site falls back to the published static tree, so members lose on-demand
compute, not their published advice.

### The outage record

Each row is one `backend-down` issue, from the uptime check that opened it to the one that
closed it. The check runs hours apart in practice (see
[free hosting](../../backend_free_hosting.md#recommendation)), so these spans bound the outages
from outside; they are not their exact lengths.

| Issue | Opened (UTC) | Closed (UTC) | Span |
| --- | --- | --- | --- |
| #747 | 2026-09-20 12:22 | 2026-09-21 13:39 | 25 h 17 min |
| #787 | 2026-09-24 05:29 | 2026-09-24 10:27 | 4 h 58 min |
| #795 | 2026-09-24 15:26 | 2026-09-25 11:14 | 19 h 48 min |
| #821 | 2026-09-25 15:51 | 2026-09-25 19:50 | 3 h 59 min |

**The logon watcher is now registered, and #821 happened after it.** Read on the PC on
2026-09-25:

- The Startup folder holds `SquadOpt advice backend.lnk`, written at 10:37:55Z. It runs
  `scripts/start_backend_at_logon.ps1 -Watch -Workers 6 -Port 8000` from the main checkout.
- The api, the six worker interpreters and `cloudflared` were created at 10:38:09Z and
  10:38:10Z. At 20:20Z they were still the same processes.
- The public check failed at 15:51Z and recovered at 19:50Z. The System log shows the PC
  asleep from 16:24:19Z to 18:23:26Z.

So the processes were alive through the whole of #821, and the watcher had nothing to restart.
It covers a process that died. It does not cover a PC that sleeps, or one that is up but not
reachable. What failed at 15:51Z, half an hour before the sleep began, was not established.

### What the backend needs, as measured

| Need | Measured or fixed value | Source |
| --- | --- | --- |
| Concurrent solves | 6 workers (the owner's launch setting and the watcher's `-Workers 6`); each worker runs one job at a time, and CP-SAT uses one search worker per solve, so 6 busy workers are 6 busy cores. `run_backend_local.ps1` pins the BLAS pools to one thread | [free hosting](../../backend_free_hosting.md), `scripts/run_backend_local.ps1` |
| Solve times on the PC | one worker, under a 15-process league build, 2026-09-17: window 1 in 3.8 to 5.4 s, a rival strategy in 18.6 to 20.6 s, window 3 in 93.0 s, window 5 in 208.5 s. Five-week windows in the league builder's 15-worker pool: 191.7 to 295.8 s | [free hosting](../../backend_free_hosting.md#historical-timing-record-2026-09-17), `src/squadopt/application/advice.py` (the comment on `WINDOW_WALL_CEILING_SECONDS`) |
| How long a member waits | the page gives up after 180, 360 or 600 s for windows 1, 3 and 5 | `web/src/features/league/advice/useAdviceJob.ts`, `PATIENCE_MS` |
| Worker memory | committed record: 177.0 to 187.1 MiB peak per worker, api 196.3 to 210.0 MiB (synthetic captures, Windows working sets, 2026-09-09). Read from the running backend on 2026-09-25 at 20:20Z: peak working set 180.0 to 217.5 MiB per worker interpreter and 201.3 MiB for the api, since their 10:38Z start | [advice capacity](../advice_capacity.md); this ADR |
| Memory used for sizing | 360 MB per worker, the top of the 250 to 360 MB recorded in the owner's run notes for the GW5 league stage on 2026-09-18. That figure is about the league builder's 15 processes, not a committed record of the backend. Six workers at 360 MB plus a 210 MiB api is 2.3 GiB | owner's run note; this ADR |
| Store (queue, cache, job specs) | 9.2 MiB in 304 files on the PC on 2026-09-25. Size is not the constraint. The constraint is the semantics: `O_EXCL` create, `os.link` create-once, mtime as a heartbeat, one store shared by the api and every worker, persistent across restarts | [ADR 0006](0006-backend-hosting.md), [runbook: store probe](../../backend_runbook.md#before-ingress-the-store-probe) |
| Inputs the backend reads | captures 46.2 MiB for all 20 on the PC, 4.2 MiB for the newest live one; handoffs 0.3 MiB; published site data 4.2 MiB in the main checkout; `artifacts/` 31.0 MiB (the Top 100 and rotation inputs) | measured on the PC, 2026-09-25 |
| CPU architecture | x86-64, by ADR 0006's parity rule, not by wheel availability (see below) | [ADR 0006](0006-backend-hosting.md) |
| Public address | `https://squadopt-api.mymandev.com`, fixed in the site build (`ADVICE_API_ORIGIN`) and in the uptime workflow | [free hosting, the tunnel](../../backend_free_hosting.md#2-the-tunnel), `.github/workflows/backend-uptime.yml` |

**What a slower CPU changes and what it does not.** The solver stops on a deterministic
budget, so on a slower core the answer stays the same as long as the wall-clock ceiling does
not bind: 1800 s for a window (`WINDOW_WALL_CEILING_SECONDS`) and 300 s for the one-week plan
(`PLAN_WALL_CEILING_SECONDS` in `src/squadopt/planning/optimizer.py`). The wait is what gets
longer. A window-5 solve that took 208.5 s on the PC would pass the page's 600 s patience on a
core up to about 2.9 times slower, before any queueing. How fast a given host's vCPU is on
this workload has not been measured anywhere.

**The ortools wheels are not the obstacle on Arm.** Checked against PyPI on 2026-09-25 at
20:04Z: `ortools==9.15.6755` publishes `cp313` `manylinux_2_28` wheels for both `x86_64` and
`aarch64`, and so does every other compiled runtime pin in `constraints.txt` (`numpy`,
`pandas`, `scipy`, `scikit-learn`, `pydantic-core`, `rpds-py`). Packaging does not require
x86-64. Three other things do tie the backend to it today:

1. ADR 0006 admits aarch64 only after its solver parity has been measured.
2. The `Dockerfile` (`FROM --platform=linux/amd64`) and `deploy/compose.yaml`
   (`platform: linux/amd64`) pin the image to amd64.
3. Azure Container Apps runs only `linux/amd64` images (see option D).

**Linux x86-64 has not been measured either.** The Dockerfile says the image does not
establish numerical equivalence with the Windows environment where the measurements were
recorded, and [the runbook](../../backend_runbook.md#the-image-and-a-local-container-run) says
that comparison has not been run. Projection exports have already been seen to differ in the
last bits between machines (`docs/issue43_handoff_acceptance.md`). So every option except the
PC needs a parity run before members use it: the same capture and requests on the PC and on
the target, with the answers compared.

**What does not move.** Under ADR 0006 the ops process stays on the PC: captures, the weekly
run, settles and site builds. A remote backend therefore still needs the PC once per publish,
to push the new inputs. Between publishes it does not.

## The options

Prices are list prices as each provider's public page or price API showed them on
2026-09-25, with no tax added and no discount applied. A month is 730 hours, the figure
Azure and Hetzner use. The page each price came from is listed under
[Sources](#sources-read-on-2026-09-25).

### A. Keep the PC, with the logon watcher registered

- **Cost.** No provider charge. Cloudflare Tunnel is free, as recorded in
  [free hosting](../../backend_free_hosting.md#2-the-tunnel) from Cloudflare's pages read on
  2026-09-17. Electricity was not measured.
- **CPU and memory.** An Intel Core i9-13900HX with 24 cores and 32 threads and 31.7 GiB of
  memory. Six workers and the api fit several times over. All the timings above were measured
  here. The machine is shared with the weekly run (a 15-process league stage) and with the
  owner's own work.
- **Persistent disk.** The NTFS system disk. The store probe passed on it on 2026-09-17. Every
  backup copy is on the same drive (audit M25). The store itself is disposable: the cache
  recomputes, and pending jobs are recomputable requests.
- **Tunnel and DNS.** No change.
- **Migration steps.** None; this is the current state. What A still lacks is outside the
  repository: the PC must not sleep while members may press Compute, and nothing restarts the
  connector when the processes are alive but the machine or its network is not serving (#821).
  A fix to how the watcher finds its repository is open as #813.
- **Rollback.** Not applicable. The fallback is the static site: let the backend stop, or
  delete the `ADVICE_API_ORIGIN` variable and release
  ([ADR 0006](0006-backend-hosting.md#rollback)).
- **What stays unsolved.** Availability depends on the owner's sleep settings, network and
  presence. Four outages in six days, the latest with the watcher running.

### B. An always-on small x86-64 VPS, with Docker Compose and cloudflared

Two providers were priced so the owner can see the range. Both are x86-64 and list a monthly
price.

| Plan | vCPU | Memory | Disk | Traffic | Listed monthly price |
| --- | --- | --- | --- | --- | --- |
| Hetzner Cloud CPX32 (Regular Performance, Nuremberg or Helsinki) | 4 shared AMD | 8 GB | 160 GB NVMe | 20 TB | €35.99 |
| Hetzner Cloud CPX42 (same) | 8 shared AMD | 16 GB | 320 GB NVMe | 20 TB | €69.99 |
| Hetzner Cloud CCX33 (General Purpose) | 8 dedicated AMD | 32 GB | 240 GB NVMe | 30 TB | €138.99 |
| DigitalOcean Basic, Regular CPU | 4 shared | 8 GiB | 160 GiB | 5,000 GiB | $48.00 |
| DigitalOcean Basic, Regular CPU | 8 shared | 16 GiB | 320 GiB | 6,000 GiB | $96.00 |
| DigitalOcean CPU-Optimized, Regular | 8 dedicated | 16 GiB | 100 GiB | 6,000 GiB | $168.00 |

Hetzner's prices were read with the page's country selector at its default, "All others",
and the page states them as including IPv4. Hetzner's cheaper Cost-Optimized line (for
example CX33, 4 vCPU and 8 GB at €8.99) was marked "not available" on 2026-09-25.

- **CPU and memory.** Six concurrent solves need six busy cores at peak, plus a little for
  the api and the connector, and 2.3 GiB. The 8 vCPU plans meet that. The 4 vCPU plans fit the memory but run at most 4
  solves at full speed, so the launch setting would drop to 4 workers or accept slower solves.
  Both providers describe their shared line as meant for variable CPU use ("workloads that can
  handle variable processor performance", Hetzner; "bursty applications", DigitalOcean). A
  solve is minutes of sustained CPU, which is why the dedicated rows are listed. Solve speed on
  any of these vCPUs is unmeasured.
- **Persistent disk.** The VM's local NVMe disk, bind-mounted by Compose. It is a real block
  device, so the store's primitives should hold, but the probe has not run there. A disk that
  dies loses only the recomputable cache and queue. DigitalOcean lists backups at 20 percent
  (weekly) or 30 percent (daily) of the droplet price. Hetzner lists backups relative to the
  instance price; the figure was not read.
- **Tunnel and DNS.** The same tunnel moves to the new host, and the DNS record (a CNAME to the
  tunnel) does not change. Cloudflare sends each request to the geographically closest
  connected replica, so two connectors in front of two different stores would split members
  across two queues. The order is:
  1. On the PC, run `start_backend_at_logon.ps1 -Unregister`, otherwise the watcher starts the
     PC's connector again.
  2. Stop the PC's connector.
  3. Copy `config.yml` and the tunnel credentials JSON to the host, and install the connector
     as a service: `cloudflared service install`, then `systemctl start cloudflared`.
     `cloudflared` publishes `linux-amd64` and `linux-arm64` builds (release 2026.9.3).
  4. Check that `cloudflared tunnel info squadopt-api` lists exactly one connector.

  The config's `service: http://127.0.0.1:8000` still matches, because Compose publishes the
  api on host loopback.
- **Migration steps in this repository.**
  1. Run the Linux x86-64 parity measurement described under Context. The image is the one
     CI's `container (linux/amd64)` job already builds. Time a window-5 solve on the chosen
     vCPU against the 600 s patience.
  2. Change `deploy/compose.yaml` in three places:
     - The worker publishes host port `127.0.0.1:9091`, so `--scale worker=6` would collide
       on it. Drop the host port for scaled workers or give them a range.
     - It mounts neither `SQUADOPT_BACKEND_ARTIFACT_ROOT` nor
       `SQUADOPT_BACKEND_CLUB_NEWS_SOURCE`. Its own comment says so. Until they are mounted,
       the Top 100 settings and the manager's word are refused by name.
     - With cloudflared on the host, the peer the api sees inside its container is not
       loopback, even though the host port is (with Docker's default port publishing it is
       normally the network's gateway address; verify it). Set `FORWARDED_ALLOW_IPS` to that
       one verified address. Otherwise every member shares one rate-limit bucket (see
       [trusted ingress](../../backend_runbook.md#trusted-ingress-for-the-container-api)).
  3. Prepare `/srv/squadopt/...` from `deploy/backend.env.example`, chown the store to
     10001:10001, start with `docker compose ... up -d`, and check `/ready`, whose store probe
     must pass on the VM's disk.
  4. Script the input transport the runbook leaves unscripted
     ([publishing what ops owns](../../backend_runbook.md#publishing-what-ops-owns)): site
     data, then the handoff, then the capture with `metadata.json` renamed into place last.
     Over SSH this is `rsync` or `scp` plus one `mv`. The capture, handoff and site data
     measured above come to under 10 MiB; `artifacts/` is 31.0 MiB in total, of which a
     publish adds only that week's files.
  5. Replace the release step. `scripts/release/restart_backend.ps1` restarts the PC's
     backend only. A remote host needs a step that deploys the image built at the release
     commit, because the commit is part of every answer's identity. No such script exists.
  6. Move the connector as above.

  The `Dockerfile` does not change, and neither does the site build or the uptime workflow,
  because the public hostname stays the same.
- **Rollback.** Stop the host's connector (`systemctl stop cloudflared`). On the PC, run
  `start_backend_at_logon.ps1 -Register` and start it. Members reach the PC again once its
  connector is up. Answers computed on the VPS are not copied back; they recompute. Jobs pending on
  the VPS at the switch are lost, and members press Compute again. Delete the VM to stop the
  charge.
- **What stays unsolved.** A single machine, now one the owner does not sleep. Nobody has
  measured solve speed on shared vCPUs. The PC is still needed once per publish.

### C. Oracle Cloud Always Free, Ampere A1 (aarch64)

- **Cost.** No charge within the allowance: 1,500 OCPU hours and 9,000 GB hours a month of
  `VM.Standard.A1.Flex`, "equivalent to 2 OCPUs and 12 GB of memory", 200 GB of block volume
  and 10 TB of outbound data a month. The two Always Free AMD instances are 1/8 OCPU and 1 GB
  each, too small for one solve. Sign-up needs a credit or debit card, used for identity
  verification. Oracle's paid x86-64 fallback, `Standard - E5`, lists $0.03 per OCPU hour and
  $0.002 per GB hour, which is $99.28 a month for 4 OCPUs and 8 GB.
- **CPU and memory.** 12 GB is ample. The CPU is not. The price list's comparison column
  prices one A1 OCPU as one vCPU and one E5 OCPU as two, so the free allowance is 2 Arm cores:
  2 concurrent solves, not 6. At full speed that means 2 workers and a queue at the deadline
  peak. Six workers on 2 cores would stretch a 208.5 s window-5 solve past the page's 600 s
  patience if the slowdown were proportional (208.5 × 3 = 625.5 s). That arithmetic is
  unmeasured on A1.
- **Persistent disk.** The boot volume, from the 200 GB block allowance: a real block device.
  The probe has not run there.
- **Tunnel and DNS.** As in B. `cloudflared-linux-arm64` exists.
- **Migration steps in this repository.** Everything in B, plus:
  1. The aarch64 parity measurement ADR 0006 asks for, and an amendment to ADR 0006 that
     admits aarch64 once it passes.
  2. The `linux/amd64` pins in the `Dockerfile` and `deploy/compose.yaml` must change, or the
     host must run without Docker. The repository has no Linux launcher: the PC's
     `run_backend_local.ps1` is Windows-specific, so that route means writing systemd units.
     Running the amd64 image under emulation would leave the parity question open and the
     solves slower.
  3. `-Workers` drops to 2.
- **Rollback.** As in B. Terminating the instance costs nothing.
- **What stays unsolved.** Oracle may reclaim an idle Always Free instance: over 7 days, CPU
  at the 95th percentile, network, and (on A1) memory all below 20 percent. An advice backend
  between deadlines fits that description. Whether reclamation also applies to an account
  upgraded to Pay As You Go is not stated on the page (UNVERIFIED). Creating an A1 instance can
  fail with "out of host capacity" for several days. The instance must be in the tenancy's
  home region. Oracle's FAQ adds that an account idle for 30 days or more may be deemed
  abandoned.

### D. Azure Container Apps with Azure Files NFS (ADR 0006's accepted topology)

- **Cost.** Consumption plan, West Europe, from the Azure retail prices API:
  - Active: $0.000034 per vCPU second and $0.000004 per GiB second.
  - Idle: $0.000004 for each.
  - The pricing page states a monthly free grant of 180,000 vCPU seconds and 360,000 GiB
    seconds per subscription.
  - A replica is billed as active while its vCPU use is above 0.01 cores or it receives more
    than 1,000 bytes a second. Whether a polling worker stays under that line was not
    measured, so each figure below is a range between all-idle and all-active:

  | Topology | vCPU / GiB billed | Compute a month |
  | --- | --- | --- |
  | ADR 0006 day one: one replica, api 0.5 vCPU / 1 GiB plus one worker 1 vCPU / 2 GiB | 1.5 / 3 | $45.14 to $158.00 |
  | Six workers: the api app plus a worker app at six replicas of 1 vCPU / 2 GiB (ADR 0006's promotion) | 6.5 / 13 | $202.82 to $709.88 |

  Add two SSD file shares at the provisioned v2 minimum of 32 GiB ($0.000196 per GiB hour,
  $9.16 a month for both) and a Basic container registry ($0.1666 a day, $5.07 a month). Log
  ingestion was not priced.
- **CPU and memory.** One replica may hold at most 4 vCPU and 8 GiB (2 vCPU and 4 GiB in a
  Consumption-only environment), and the containers in it must sum to an allowed pair. The
  day-one 1.5 vCPU / 3.0 GiB is an allowed pair, which settles one of the fields
  `deploy/containerapp.yaml` marks UNVERIFIED. Memory is allocated at 2 GiB per vCPU, more
  than five times what a worker was measured to use. It is billed all the same.
- **Persistent disk.** Container Apps mounts only classic Azure file shares, created in a
  storage account. It does not mount the newer `Microsoft.FileShares` resource. NFS is SSD
  only. Read on 2026-09-25, the NFS mount has three requirements:
  - The environment needs a custom VNet, and the storage account must allow access from it.
  - The storage account must not require encryption in transit for NFS.
  - Ports 445 and 2049 must be open on the subnet's security group.

  The provisioned v1 model has a 100 GiB floor per share; provisioned v2 SSD has 32 GiB. The
  runbook's Azure table records a 100 GiB floor for both shares. That is true only of v1, and
  it can be corrected when the table is next applied. The store probe has never run against an
  Azure Files NFS share ([runbook](../../backend_runbook.md#before-ingress-the-store-probe)).
- **Tunnel and DNS.** Two ways, and in both the public hostname stays the same:
  - **Keep the tunnel.** Run `cloudflared` as one more container in the api's replica. The
    containers of one app share network resources, so the api's peer stays loopback and the
    existing forwarded-address trust holds. The api container plus a 0.25 vCPU / 0.5 GiB
    connector sums to 0.75 / 1.5, an allowed pair once the worker has moved to its own app.
  - **Drop the tunnel.** Use Container Apps ingress with `squadopt-api.mymandev.com` as a
    custom domain, which changes the DNS record. How the managed certificate and the ingress
    peer behave behind Cloudflare's proxy is UNVERIFIED.
- **Migration steps in this repository.**
  1. The same parity measurement as B.
  2. Amend `deploy/containerapp.yaml`. For six workers it needs ADR 0006's promotion: the
     worker in its own app at six replicas. It needs the `cloudflared` container, or the
     custom domain. And it lacks the same two switch inputs as the Compose file.
  3. Follow the runbook's
     [Azure Container Apps](../../backend_runbook.md#azure-container-apps) and
     [preparing the shared mount](../../backend_runbook.md#preparing-the-shared-mount)
     sections.
  4. Script the transport of inputs from the PC to an NFS share inside a VNet, which the
     runbook records as undecided.
  5. Write a release step that re-applies the YAML with the release digest.
- **Rollback.** The runbook's own: re-apply the previous digest, or for hosting, stop the
  cloud connector (or remove the custom domain) and re-register the PC watcher. Delete the
  resource group to stop all charges.
- **What stays unsolved.** The widest cost range at six always-on workers, the highest at its
  upper end, and the most setup (VNet, storage account, registry, identity). The repository's Azure files are templates with
  placeholder subscription, registry and storage names, and none has been applied.

### E. AWS ECS on Fargate with EFS (ADR 0006's recorded alternative)

- **Cost.** Linux x86-64 in Frankfurt, from AWS's price list files published 2026-09-11:
  $0.04656 per vCPU hour and $0.00511 per GB hour. Six workers at 1 vCPU / 2 GB plus an api
  task at 0.5 vCPU / 1 GB is 6.5 vCPU and 13 GB: $269.42 a month. The day-one single worker
  (1.5 vCPU / 3 GB) is $62.17. Tasks that reach the internet by public address pay $0.005 per
  IPv4 address per hour, $3.65 a month each: $25.55 for seven tasks. EFS Standard storage is
  $0.36 per GB-month, and the Elastic throughput mode adds $0.04 per GB read and $0.07 per GB
  written. The store and inputs are under 0.1 GB. The container registry was not priced.
- **CPU and memory.** Sized per task, so six 1 vCPU workers is exactly six cores. Arm
  (Graviton) Fargate is cheaper ($0.03725 per vCPU hour) and falls under the same aarch64 rule
  as C.
- **Persistent disk.** EFS speaks NFSv4.1, and AWS describes it as providing "strong data
  consistency and file locking". Hard-link support was not confirmed on an AWS page today
  (UNVERIFIED). The store probe decides, and it has never run on EFS.
- **Tunnel and DNS.** Run `cloudflared` as a second container in the api task. Containers in
  one `awsvpc` task share its network namespace, a fact taken from ECS's documented model and
  not re-read today. The hostname and DNS stay as they are, and no load balancer is needed.
- **Migration steps in this repository.** The same parity measurement and transport script as
  B and D. A task definition, which the repository does not have (only Compose and the Azure
  YAML exist). The same two switch inputs. A release step.
- **Rollback.** As in D: stop the cloud connector, re-register the PC watcher, and delete the
  service and the file system.
- **What stays unsolved.** A cost at six workers that falls inside D's range, a template that
  does not exist yet, and a filesystem whose hard-link behaviour is unproven here.

## Comparison

| | A. PC | B. x86-64 VPS | C. Oracle A1 free | D. Azure Container Apps | E. AWS Fargate + EFS |
| --- | --- | --- | --- | --- | --- |
| Listed monthly cost | none listed | €35.99 (4 vCPU) or €69.99 (8 vCPU) at Hetzner; $48 or $96 at DigitalOcean | $0 in the allowance; $99.28 for Oracle x86 E5 at 4 OCPU / 8 GB | $202.82 to $709.88 for six workers, plus $14.23 for files and registry | $269.42 for six workers, plus $25.55 for IPv4 and EFS |
| Concurrent solves at full speed | 6 and more | 4 or 8, on shared vCPU | 2 | 6 (one per replica) | 6 (one per task) |
| Memory against 2.3 GiB | 31.7 GiB | 8 or 16 GB | 12 GB | 13 GiB billed | 13 GB billed |
| Store | NTFS, probe passed 2026-09-17 | local NVMe, probe not run | block volume, probe not run | Azure Files NFS in a VNet, probe not run | EFS, probe not run, hard links unconfirmed |
| Parity measured | yes (the measurements were taken here) | no (Linux x86-64) | no (aarch64, and ADR 0006 must admit it) | no (Linux x86-64) | no (Linux x86-64) |
| Tunnel or DNS change | none | move the connector; DNS unchanged | move the connector; DNS unchanged | connector container, or custom domain and DNS | connector container; DNS unchanged |
| Repository changes before use | none | `deploy/compose.yaml` (3), transport script, release step | as B, plus `Dockerfile` and Compose platform, 2 workers | `deploy/containerapp.yaml` (split, connector, inputs), transport, release step | a task definition, transport, release step |
| Up while the owner's PC sleeps | no | yes | yes, unless reclaimed | yes | yes |
| Needs the PC per publish | yes | yes | yes | yes | yes |

## Decision

None yet. The owner chooses. When he does:

- this record's status becomes accepted and names the option;
- if the choice changes ADR 0006's topology or admits aarch64, ADR 0006's status line records
  that too;
- the repository changes listed under that option are opened as their own pull requests, the
  parity measurement first.

## Suggested order (for the owner to decide)

This is an order to consider the options in, with the reason for each place. It is not a
recommendation, and every step can stop the sequence.

1. **A, as it is now, with the owner-side gaps closed.** It costs nothing and is the only
   option whose timings were measured. The latest outage coincided with a sleep window, so the
   PC's sleep setting comes first.
2. **Measure before moving anything.** The Linux x86-64 parity run and a timed window-5 solve
   are prerequisites for B, D and E. The cheapest way to run them is an hourly-billed VM
   (Hetzner lists CPX42 at €0.1122 an hour). This step answers the unknown every remote
   option shares.
3. **B, if outages continue after step 1.** It is the lowest listed monthly price that meets six
   workers on x86-64 (€69.99). It runs the existing Compose file with three changes. It keeps
   the same tunnel and hostname. Its rollback is a few commands on two machines.
4. **C, if a zero price outweighs its conditions.** Those conditions are: an aarch64 parity
   measurement and an ADR 0006 amendment, a Dockerfile and Compose change, 2 workers instead of
   6, a card on file, capacity errors at creation, and the idle-reclamation rule.
5. **D or E, if managed restarts and replacement matter more than price.** D is already ADR
   0006's accepted topology, so choosing it needs no new architecture decision, only the most
   setup and the highest listed cost at six workers. E is its recorded alternative, with a
   template still to write.

## Rollback

Each option lists its own. Every one of them ends in the same safe state: with no backend
answering, the site serves the published static tree ([ADR 0006](0006-backend-hosting.md#rollback)),
and no member sees wrong advice.

## When to revisit

Revisit when an outage happens on the chosen host, when a price listed here changes, when
Hetzner's Cost-Optimized line becomes available again, when the parity measurement reports,
or when the league grows past what six workers serve at the deadline (the capacity record's
own trigger).

## Sources, read on 2026-09-25

All were read on 2026-09-25 between 20:03 and 20:25 UTC. The pricing pages that render prices
in the browser (Hetzner, Oracle, Azure) were read after rendering; the API and price-list files
were read as JSON.

| What | Where |
| --- | --- |
| Hetzner Regular Performance (CPX) prices | <https://www.hetzner.com/cloud/regular-performance/> |
| Hetzner General Purpose (CCX) prices | <https://www.hetzner.com/cloud/general-purpose/> |
| Hetzner Cost-Optimized (CX, CAX) availability | <https://www.hetzner.com/cloud/cost-optimized/> |
| DigitalOcean droplet prices | <https://www.digitalocean.com/pricing/droplets> |
| Oracle Always Free resources and idle reclamation | <https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm> |
| Oracle Free Tier FAQ (card, capacity errors, idle accounts) | <https://www.oracle.com/cloud/free/faq/> |
| Oracle compute price list (A1, E5, block volume) | <https://www.oracle.com/cloud/price-list/#pricing-compute> |
| Azure Container Apps pricing (free grant, active and idle rules) | <https://azure.microsoft.com/en-us/pricing/details/container-apps/> |
| Azure retail prices, Container Apps, West Europe | <https://prices.azure.com/api/retail/prices> filtered on `serviceName eq 'Azure Container Apps' and armRegionName eq 'westeurope'` |
| Azure retail prices, Files and Container Registry, West Europe | the same API, `serviceName eq 'Storage'` and `'Container Registry'` |
| Azure Files pricing (v2 SSD included IOPS and throughput) | <https://azure.microsoft.com/en-us/pricing/details/storage/files/> |
| Azure Files billing models (share minimums, NFS on SSD) | <https://learn.microsoft.com/en-us/azure/storage/files/understanding-billing> |
| Container Apps CPU and memory pairs, amd64 only | <https://learn.microsoft.com/en-us/azure/container-apps/containers> |
| Container Apps storage mounts (classic shares, NFS needs VNet) | <https://learn.microsoft.com/en-us/azure/container-apps/storage-mounts> |
| AWS Fargate prices, Frankfurt | <https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonECS/current/eu-central-1/index.json> (published 2026-09-11) |
| AWS EFS prices, Frankfurt | <https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEFS/current/eu-central-1/index.json> (published 2026-09-11) |
| AWS public IPv4 price, Frankfurt | <https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonVPC/current/eu-central-1/index.json> (published 2026-09-17) |
| EFS overview (NFSv4.1, consistency and locking) | <https://docs.aws.amazon.com/efs/latest/ug/> |
| Tunnel replicas: closest-replica routing | <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-availability/> |
| Tunnel limits: 25 active replicas per tunnel | <https://developers.cloudflare.com/cloudflare-one/account-limits/> |
| cloudflared as a Linux service | <https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/do-more-with-tunnels/local-management/as-a-service/linux/> |
| cloudflared release assets (linux-amd64, linux-arm64) | <https://github.com/cloudflare/cloudflared/releases/tag/2026.9.3> |
| ortools and the other compiled pins, wheel tags | `https://pypi.org/pypi/<name>/<version>/json` for every pin in `constraints.txt` |
| Outage issues | #747, #787, #795, #821 |
| PC facts: CPU, memory, Startup shortcut, process start times, sleep log, store and input sizes | read-only queries on the owner's PC; no process was touched |
