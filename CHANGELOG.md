# Changelog

Software releases, newest first. A release label says which *code* this is; it is not an
operational identifier. What decided a particular squad is recorded with that decision —
`model_name`, `model_version`, `feature_contract_version`, `report_contract_version`,
`prediction_fingerprint` and the CLI's `repository_commit` — and no version number here
replaces any of them.

Versions follow [semantic versioning](https://semver.org/). `docs/architecture/branching.md`
records how the `v<semver>` tag namespace relates to the operational `run-*` and `site-*` ones.

## 1.0.0

**What this release is: the system that made and published the first live decision.**

That is a statement about something already done and immutable, which is the only kind of
thing a release label should assert. It is deliberately not "the system we think is ready" —
nothing pending can retroactively make it false.

The decision it names, every value read back from the published view
(`web/public/data/2026-27/gw01/recommendation.json`) rather than transcribed from a run log:

| | |
| --- | --- |
| Season / gameweek | 2026-27, gameweek 1 (`decision_kind: opening`) |
| Capture | `fpl-live-20260821T143619Z-11bc603a8e1c`, taken 2026-08-21T14:36:19Z |
| Deadline | 2026-08-21T17:30:00Z |
| Projected score | 56.077499304365105 |
| Solver | `OPTIMAL`, `solver_proved_optimal: true` |
| Squad cost | 100.0 of 100.0 |
| Captain multiplier | 2 |
| Players excluded as unavailable | 96 |
| Published as | `site-2026-27-gw01-decision` |

Contracts in force for that decision:

| Contract | Version |
| --- | --- |
| Model | `squadopt-deterministic-baseline` / `opening-carry-over-v1` |
| Features | `opening-carry-over-features-v1` |
| Report | `live_recommendation_v3` |
| Season rules | `season_rules_v1` (fingerprint `6aa14f8b…`) |
| Published view | `ui_view_v1` |
| Season tick | `season_tick_v1` |
| Prediction fingerprint | `7a056a4b2c52630c2c4c5835aa8c1a52031a8c69abf99df152d46f6baa8563df` |

### Added

- `squadopt.__version__`, read from the installed distribution's metadata rather than written
  down a second time.

### Changed

- `pyproject.toml` version from `0.1.0` — which had never meant anything, unchanged since the
  first commit — to `1.0.0`.
- `docs/architecture/branching.md` now documents the four tag namespaces, including that
  `v2026-27.gw01` is a pre-taxonomy season pointer occupying `v*` and is not a software
  version.

### Deliberately unchanged

- **No version field in `/api/v1/info`.** `ApiServiceInfo` refuses overrides and
  `tests/integration/test_backend_api.py` asserts the response equals it exactly, so one added
  field would mean `backend_api_v1` → `v2`. Nothing reads it: there is no reference to
  `/api/v1/info`, `/health` or `api_version` anywhere in `web/src`, which pins `ui_view_v1` for
  the data views and never touches the service payload. Publishing a number nothing reads is the
  failure mode #145 cleaned out of `branching.md` — recorded values that had quietly drifted
  because nothing depended on them — and this does not reintroduce it at a contract boundary.
- `platform/api_contract.py`, `BACKEND_API_CONTRACT_VERSION`, `ui_view_v1`.

## Release procedure

1. Bump `[project].version` in `pyproject.toml` on `develop`, with the changelog entry in the
   same pull request.
2. Merge to `main` through the normal release path and wait for the `main`-push CI to be green.
3. The release owner places the annotated `v<semver>` tag on that `main` commit. Tags are never
   moved or reused.

One caveat that has bitten already: `squadopt.__version__` reports the version of the
**installed** distribution, not of the working tree. After a bump, an editable install still
reports the old number until it is refreshed:

```console
python -m pip install -e . --no-deps
```

This is a property of reading the number from one place rather than copying it, and refreshing
is cheaper than the drift a second copy would cause. A fresh CI install never sees it.
