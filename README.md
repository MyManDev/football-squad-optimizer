# SquadOpt

SquadOpt turns captured Fantasy Premier League data into reproducible squad decisions and
published league-member views. It combines a Python decision engine, a React member website
and an optional advice API with independent workers.

Start with the [documentation guide](docs/README.md), the
[current system map](docs/architecture/system_map.md) or the
[product and research roadmap](docs/product/roadmap.md).
[ADR 0007](docs/architecture/decisions/0007-enterprise-transition.md) records the enterprise
transition: what it changed, what was accepted and what still waits on a real environment.

## Repository layout

| Path | Responsibility |
| --- | --- |
| `src/squadopt/contracts/` | Shared player vocabulary and canonical ordering |
| `src/squadopt/` engine packages | Captures, projections, optimization, planning and evaluation |
| `src/squadopt/application/` | Typed advice, evidence and publication workflows |
| `src/squadopt/platform/` | Queue, workers, storage, capture adapters and operational entry points |
| `src/squadopt/api/` | Optional HTTP adapter over application/platform contracts |
| `scripts/` | Compatible repository commands and research entry points |
| `web/` | Member website, runtime publication validation and browser tests |
| `deploy/` | Deployment configuration for separate API and worker processes |
| `tests/` | Offline fixtures, unit tests and opt-in acceptance probes |
| `docs/` | Product, operations, architecture, contracts and scientific evidence |
| `data/` | Private local operational state; a Git checkout is not its backup |
| `notebooks/` | Exploration only; every notebook calls importable `src/squadopt/` code |
| `constraints.txt` | Pinned package versions the container and measurement checks install |
| `artifacts/` | Git-ignored local experiment outputs; generated, never source |
| `.codex-tmp/` | Git-ignored agent worktrees and scratch; not project content |

## Where to make a change

| Task | Start here |
| --- | --- |
| League/member pages and scoreboard display | [League UI](web/src/features/league/) and [publication builder](src/squadopt/application/league_views.py) |
| Other website screens | [Features](web/src/features/), [shared design](web/src/design/) and [translations](web/src/i18n/) |
| Published JSON shape and frontend validation | [Versioned contracts](docs/contracts/) and [web data adapters](web/src/data/) |
| Advice generation | [Advice workflow](src/squadopt/application/advice.py), then [planning](src/squadopt/planning/) and [optimization](src/squadopt/optimization/) |
| Captured inputs and prediction | [Data](src/squadopt/data/), [features](src/squadopt/features/) and [prediction](src/squadopt/prediction/) |
| Settled results and decision history | [Live records](src/squadopt/live/), [evaluation](src/squadopt/evaluation/) and [scoreboard](src/squadopt/application/scoreboard.py) |
| Weekly commands and publication | [CLI](src/squadopt/platform/cli.py), [weekly operations](src/squadopt/platform/weekly_operations.py) and [weekly runbook](docs/weekly_runbook.md) |
| HTTP requests and queued advice | [API](src/squadopt/api/), [advice worker](src/squadopt/platform/advice_worker.py) and [backend runbook](docs/backend_runbook.md) |
| Research or reproducing a measurement | [Experiments](src/squadopt/experiments/), [script catalog](scripts/README.md) and [evidence index](docs/measurements_index.md) |
| Tests | [Python unit](tests/unit/), [integration](tests/integration/) and frontend tests beside their features |

Use the [dependency rules](docs/architecture/dependency_rules.md) before moving Python modules.
The [script catalog](scripts/README.md) separates operational commands, research runners and
compatibility entry points. The [documentation guide](docs/README.md) groups documents by topic;
historical record paths also appear in code and provenance.

## Development

Python 3.11 is the supported floor. Python 3.13 with `constraints.txt` reproduces the pinned
package versions used by the container and measurement checks:

```powershell
python -m venv .venv
.venv/Scripts/python -m pip install -c constraints.txt -e ".[api,dev]"
.venv/Scripts/python -m squadopt.platform.cli --help
```

For Python 3.11, install the declared ranges without `-c constraints.txt`. For the website,
use Node 22, run `npm ci` in `web/`, then `npm run dev`. See
[Contributing](CONTRIBUTING.md) and the [web guide](web/README.md) for the checks CI runs.

### Do the work in a worktree, not in this checkout

Branch and edit in a git worktree. Leave the main checkout on `develop`, clean.

```console
git worktree add .codex-tmp/worktrees/<name> -b <branch> origin/develop
```

Two reasons, and both have already cost time.

**The weekly run executes from this checkout and refuses three ways.** A modified tree raises
`Weekly evidence requires a clean source checkout`. A `HEAD` that is not the declared revision
raises on the mismatch. And `check_publication_base` refuses when the checkout is not at
`origin/develop`. The third is the one a "is it clean, is it behind" glance misses, and all three
land at preflight on a deadline afternoon, after the solve has been spent. Check with:

```console
git fetch origin && git merge --ff-only origin/develop
```

**Branching from this checkout carries whatever it is standing on.** `git switch -c` from a
`develop` that is not at `origin/develop` puts someone else's commit on your branch, and a squash
merge then bundles two unrelated changes under one message. That happened on 2026-09-14: a
documentation pull request absorbed a web feature, and the feature's own pull request closed
itself as empty because its content had already landed. Nothing was lost and both changes were
gate-tested together, but the history now describes half of what it contains. Branching from
`origin/develop` explicitly, as above, cannot do this.

A worktree is cheap and disposable. `git worktree remove <path>` when the branch has merged, and
never delete a directory another worktree is using: on Windows a recursive delete follows
directory junctions and takes the target's contents with it, which is how the live captures were
lost on 2026-09-10.

## Running the system

The member flow accepts league `352490`, then a selected member. Other leagues are currently
rejected. Published advice and a newly computed response are separate states; pure-points
requests and rival strategies support one, three or five weeks, and a rival strategy needs a
named member. Published capabilities control what the page offers; the
[roadmap](docs/product/roadmap.md#current-position) lists what a member gets today.

Use the [weekly runbook](docs/weekly_runbook.md) for publication, the
[backend runbook](docs/backend_runbook.md) for API/worker acceptance, and the
[operations inventory](docs/architecture/operations_inventory.md) for the discovered hosting
state and Compose startup. Runtime paths must refer to prepared persistent storage and
captured inputs. Source configuration alone does not establish a deployed backend.

Private captures, the decision ledger and advice records need a separately verified backup.
The [backup and recovery procedure](docs/architecture/backup_recovery.md) describes manifests,
trusted receipts and restore verification.

## Evidence and model promotion

Installing research code does not activate an experimental model. Phase D/E admission gates,
prospective captures and settled outcomes determine scientific claims. Historical measurement
artifacts retain their paths and provenance; see the [research guide](docs/research/README.md)
and [roadmap](docs/product/roadmap.md).
