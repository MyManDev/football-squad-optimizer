# SquadOpt

SquadOpt turns captured Fantasy Premier League data into reproducible squad decisions and
published league-member views. It combines a Python decision engine, a React member website
and an optional advice API with independent workers.

Start with the [documentation guide](docs/README.md), the
[current system map](docs/architecture/system_map.md) or the
[product and research roadmap](docs/product/roadmap.md). The
[enterprise transition record](docs/architecture/enterprise_transition.md) distinguishes
implemented changes, completed checks and outstanding operational acceptance.

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
[Contributing](CONTRIBUTING.md) and the [web guide](web/README.md) for the required checks.

## Running the system

The member flow accepts league `352490`, then a selected member. Other leagues are currently
rejected. Published advice and a newly computed response are separate states; pure-points
requests support one, three or five weeks, while rival strategies require a named member and
one week. Published capabilities control what the page offers.

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
