# Notebooks

Exploration only. Core logic lives in importable modules under `src/squadopt/`, and
every notebook calls those functions rather than reimplementing them. A notebook is
never the only implementation of anything.

| Notebook | Purpose |
| --- | --- |
| `01_data_eda.ipynb` | Inspect the data pipeline against the synthetic sample: panel shape, quality, feature timing, projection table |

## Conventions

**Outputs are not committed.** Clear them before committing, so diffs stay readable
and stale results cannot be mistaken for current ones. A test enforces this.

**No plotting.** Charting would add a dependency Sprint 0 does not otherwise need,
so exploration is table-based. If plots become worthwhile, add the library under a
separate optional-dependency group rather than to the project's runtime
requirements, and agree that change with the team first.

## Running

```powershell
.venv\Scripts\python -m pip install jupyter
.venv\Scripts\python -m jupyter lab
```

Jupyter is not a project dependency; install it into the local environment when you
need it. The notebooks locate the repository root themselves, so the working
directory does not matter.

For the full chain including the solver, prefer the script:

```powershell
.venv\Scripts\python -m scripts.run_pipeline_demo
```
