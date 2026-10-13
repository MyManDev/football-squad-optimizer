# System map

SquadOpt is one installed, layered Python package with separate HTTP and worker processes,
and a React website. The [dependency rules](dependency_rules.md) define the enforced import
order; [ADR 0001](decisions/0001-modular-monolith.md) explains the modular monolith choice.
This map describes the enterprise transition source. The earlier graph/count audit remains
available in Git at `6ca49686:docs/architecture/system_map.md`.

## Boundaries

| Area | Responsibilities and dependency direction |
| --- | --- |
| `contracts` | Player positions, required projection columns and stable ordering; imports no engine layer |
| `data`, `features`, `prediction` | Captured data, features and projections |
| `optimization`, `planning` | Decisions and plans; shared constraints/selection/verification live in `optimization.decisions` |
| `evaluation` | Scoring, promotion policy and bootstrap statistics shared by experiments and backtests |
| `scenarios` | Joint point scenarios, scenario paths and rival squads; domain, not research: `live` (plan selection, report, risk) and `application` import it |
| Research packages | Search, preflight, recalibration, backtests and experiments; obey the declared layer order |
| `live` | Domain records, decisions, advice and settled operational calculations |
| `application` | Typed workflows, publication/evidence builders, advice capabilities and squad optimization from a canonical projection CSV (`projection_csv`); no platform or script imports |
| `platform` | Filesystem, capture, queue, process pool, metrics, backup and command adapters |
| `api` | HTTP translation; engine access goes through platform/application boundaries |
| `integration` | One module that re-exports `optimize_squad_from_csv` from `application.projection_csv` for one release; imports only `application` |
| `web` | Static publication reader, validated HTTP advice client, member selection and rendering |
| Device solver | The member's one-week plan solved in the browser with HiGHS, from the published device-plan table; lives in `web/src/features/league/device/` |
| Measurement preflight | Required root fields declared per artifact kind in `preflight.measurement`; checks declared governance, proves nothing about the actions. See [evidence validation](evidence_validation.md) |
| Solver helpers | Squad/lineup invariants shared by the live squad and transfer paths through `optimization.decisions`. See [solver boundaries](solver_boundaries.md) |

The five former import exceptions are removed: vocabulary moved to `contracts.players`,
and the common policy/statistics moved from `experiments` to `evaluation`. Original import
locations retain compatibility exports. `lint-imports` enforces the order with zero baseline
exceptions and a separate prohibition on direct API-to-engine imports.

## Advice request

```mermaid
flowchart LR
    W[Member website] --> P[Published views]
    W --> A[HTTP API]
    A --> C[Validated cached response]
    A --> Q[Persistent job queue]
    Q --> J[Independent worker processes]
    I[Captured inputs and retained handoff] --> J
    J --> E[Application and decision engine]
    E --> C
    J --> M[Worker metrics]
    A --> N[API metrics]
```

API and workers share durable queue/cache storage. A permanent OS-backed lock serializes
queue transitions; recovery retains queued intent and isolates corrupt records. Attempt
identity fences stale workers from writing a terminal response. See
[queue recovery](queue_recovery.md) and [advice boundaries](advice_boundaries.md).
Worker counters remain in the worker process and are scraped independently from the API.

## Device solve

```mermaid
flowchart LR
    R[Weekly run] --> T[Device-plan table per capture]
    T --> P[Published views]
    W[Member website] --> P
    W --> D[Web Worker with HiGHS]
    D --> V[One-week plan on the member's device]
```

The weekly run publishes, once per capture, the inputs the server's own solver receives for a
member's one-week plan ([`league_device_plan_v1`](../contracts/league_device_plan_v1.md)). The
member page states the same problem in a Web Worker and solves it with HiGHS compiled to
WebAssembly, so a one-week plan, a chip week, a rival strategy and a Top 100 weight need no
backend. Three- and five-week windows are still answered by the advice backend. The direction
is device-first computation (issue #978).

## Deployment units

The system runs as separate units: the static website on Cloudflare Pages, the device solver in
the member's browser, the weekly run and the installed CLI on the operator's machine, the advice
API and its worker processes from one container image or natively on the owner's PC, the FPL
probe Worker, and the scheduled backend uptime check on GitHub Actions. The
[architecture overview](../../ARCHITECTURE.md#4-deployment-units) gives each unit's code, entry
point, state and present host.

## Publication and recovery

Capture adapters produce private snapshots. Typed application builders consume captured
inputs to produce evidence, retained handoffs, league views, the site and scoreboard.
Platform adapters own network/Git operations and process workers; repository scripts retain
compatible CLI entry points. The installed weekly runner journals stages and verifies
artifacts before resuming a run. What the transition accepted and what still waits on a real
host is recorded in [ADR 0007](decisions/0007-enterprise-transition.md).

Projection handoffs retain their capture/content-addressed originals before the compatibility
alias changes. Backup inventory and trusted receipts establish byte integrity; restore into
an empty target checks it again. Neither Git nor the public website replaces private-state
backup. See [recovery](backup_recovery.md) and [operations inventory](operations_inventory.md).

## Website responsibilities

The member route owns loading/error states. Dedicated hooks own publication queries and
advice selection/job state. The member view composes pure rendering sections. Runtime
publication validators and shared errors are independent of HTTP loaders. Compatibility
exports preserve existing callers. See [member page boundaries](member_page_boundaries.md).

## Verification and limits

Run `lint-imports`, strict mypy, Ruff and the full offline Python suite; then web type/lint,
unit, production-build and browser gates. Installed-package tests verify publication does
not depend on `scripts/`. Opt-in probes establish cross-language publication, real
API/worker/browser, container, and concurrent-load behavior in their measured environments.

Remote storage locking, restart survival, external restore, scheduled-run delivery and a
production replica count require acceptance in that environment. A local pass does not
establish those facts. Scientific promotion still requires its own measured evidence.
Wide legacy package exports and remaining research scripts are compatible existing seams;
this transition does not rename immutable measurements or silently enable experimental models.
