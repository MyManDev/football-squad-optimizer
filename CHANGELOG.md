# Changelog

Software releases, newest first. A release label says which *code* this is; it is not an
operational identifier. What decided a particular squad is recorded with that decision —
`model_name`, `model_version`, `feature_contract_version`, `report_contract_version`,
`prediction_fingerprint` and the CLI's `repository_commit` — and no version number here
replaces any of them.

Versions follow [semantic versioning](https://semver.org/). `docs/architecture/branching.md`
records how the `v<semver>` tag namespace relates to the operational `run-*` and `site-*` ones.

## Unreleased

Changes on `develop` since 1.0.0 that no software version names yet. The project version stays
`1.0.0` until the owner decides whether the next one is 2.0.0, an open question in
[ADR 0010](docs/architecture/decisions/0010-clean-architecture-rings-and-repository-layout.md).

### Site releases since 1.0.0

The code on `develop` reached members through the operational `site-*` tags below. Each names a
deployed site artifact, not a software version, and each decision it published is identified
by its own `model_version`, `prediction_fingerprint` and `repository_commit`. The list is the
`site-*` tags on GitHub dated after `v1.0.0`, as read on 2026-10-13; `branching.md` explains why
the tag list is not a complete record of what was deployed.

| Tag | Tagged | Release commit |
| --- | --- | --- |
| `site-2026-27-gw01-settled` | 2026-08-25 | Pull request #252 |
| `site-2026-27-gw04-decision` | 2026-09-09 | Release commit: the gameweek 4 decision view and the day's fixes |
| `site-2026-27-gw04-settled` | 2026-09-16 | Pull request #574 |
| `site-2026-27-gw04-settled-2` | 2026-09-17 | Pull request #593; its dispatch was refused and it deployed nothing (`branching.md`, tag namespaces) |
| `site-2026-27-gw05-decision` | 2026-09-18 | Pull request #619 |
| `site-2026-27-gw05-settled` | 2026-09-22 | Pull request #780 |
| `site-2026-27-gw06-decision` | 2026-09-23 | Pull request #784 |
| `site-2026-27-gw06-fix1` | 2026-09-25 | Pull request #805, the direction D site |
| `site-2026-27-gw06-fix2` | 2026-09-26 | Pull request #852 |
| `site-2026-27-gw06-fix3` | 2026-09-26 | Pull request #868 |
| `site-2026-27-gw06-fix4` | 2026-09-28 | Pull request #882: scoring consistency and mobile decision clarity |
| `site-2026-27-gw06-fix5` | 2026-09-29 | Pull request #892: visible member plan settings |
| `site-2026-27-gw06-fix6` | 2026-10-01 | Pull request #908: guarded football planning |
| `site-2026-27-gw06-fix7` | 2026-10-01 | Pull request #910: conditional football information planning |
| `site-2026-27-gw06-fix8` | 2026-10-01 | Pull request #913: complete football policy comparisons |
| `site-2026-27-gw06-fix9` | 2026-10-01 | Pull request #916 |
| `site-2026-27-gw06-fix10` | 2026-10-02 | Pull request #918: football news integration |
| `site-2026-27-gw06-fix11` | 2026-10-02 | Pull request #920: official FPL information and football decision improvements |
| `site-2026-27-gw06-fix12` | 2026-10-02 | Pull request #928: the current experimental football model for GW6 |
| `site-2026-27-gw06-fix13` | 2026-10-03 | Pull request #947 |
| `site-2026-27-gw06-fix14` | 2026-10-03 | Pull request #952 |
| `site-2026-27-gw06-fix15` | 2026-10-04 | Pull request #965 |
| `site-2026-27-gw06-fix16` | 2026-10-05 | Pull request #970 |
| `site-2026-27-gw06-fix17` | 2026-10-10 | Pull request #1073 |

### Removed (pull request #1080)

- 44 retired measurement and artifact runners, each listed under "Retired runners" in the
  [script catalogue](scripts/README.md) with how to restore and run it, and
  `scripts/release/queue2.sh`, unused since `develop` merges through the merge queue.
- The `squadopt.risk` and `squadopt.uncertainty` packages, and the laboratory modules only the
  retired runners used, including the shadow calibration lane.
- 49 unused definitions in kept modules, with their tests.
- The unused web dependencies `dompurify`, `marked` and `@types/react-router`.
- `notebooks/` and six unreferenced pull request screenshots.

Committed records under `docs/` stay as evidence (ADR 0003).

## 1.0.0

**What this release is: the first software release cut after the system's first live decision.**

The distinction matters, because the tag does not sit on the commit that produced that
decision — it sits on a later release commit. What the label points at is something already
done and immutable, which is the only kind of thing a release label should assert. It is
deliberately not "the system we think is ready": nothing pending can retroactively make it
false.

The decision it comes after, read back from the record rather than transcribed from a run log.
Most rows come from the published decision view
(`web/public/data/2026-27/gw01/recommendation.json`); the two that do not are marked, because a
table that says "all of this came from one file" when it did not is the kind of small untruth
this project spends its time removing:

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
| Published as | `site-2026-27-gw01-decision` *(release tag, not a field of the view)* |

Contracts in force for that decision:

| Contract | Version |
| --- | --- |
| Model | `squadopt-deterministic-baseline` / `opening-carry-over-v1` |
| Features | `opening-carry-over-features-v1` |
| Report | `live_recommendation_v3` |
| Season rules | `season_rules_v1` (fingerprint `6aa14f8b…`) |
| Published view | `ui_view_v1` |
| Season tick | `season_tick_v1` *(from `status.json`, not the decision view)* |
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
