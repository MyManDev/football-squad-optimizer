# Local advice backend validation — D1

The existing API and worker completed a real cache miss → submission → queued/running →
completed → cache hit cycle on 2026-09-08. No application, API, worker, deployment or web
code was changed for this validation. This proves the local HTTP/worker path only; browser
integration, static fallback and hosted storage remain unverified by this run.

## Inputs and execution

- Code: `6b96ff029c5c5c23839181f611e4acd56cf0e29c`, the fetched `origin/develop` at execution.
- Branch: `feat/serving-backend`, in the single `.codex-tmp/worktrees/backend` worktree.
- Capture: `fpl-live-20260907T131414Z-db9314d00961`, the newest live capture in the existing
  main checkout's `data/snapshots` directory. The resolved context was `2026-27`, GW4.
- Handoff: the existing `data/handoffs/2026-27-gw04.json`, with matching source capture.
- Registry: the existing `data/entries/registry.json`. Its league and first two entries
  selected the member and rival; the backend itself reads membership from the published tree.
- Published tree: this worktree's `web/public/data`, without regeneration or modification.
- Request: `fark-yarat`, window `1`, with the registry's second member as the rival. This
  combination is absent from the member's static advice tree.
- Output: a fresh `.pt/d1/store`, shared by two separate local processes. No mock compute,
  cache preloading, input copying, junction or symlink was used.

The existing main-checkout virtual environment ran both processes, with `PYTHONPATH` set to
this worktree's `src` and root. The imported `squadopt.__file__` was verified to be inside
the worktree. `PYTHONDONTWRITEBYTECODE=1` prevented imported modules creating bytecode, and
process temporary files were directed to `.pt/d1/tmp`.

The API command was `python -m uvicorn --factory squadopt.api.runtime:build_app --host
127.0.0.1 --port <local-port>`. The worker command was `python -m
squadopt.platform.advice_worker --max-jobs 1 --idle-seconds 0.25`. Both used the same store,
site, snapshot, handoff and commit environment settings, recorded in the local evidence.

## Observed exchange

The table summarizes one run. Every request, poll, exact response body/header and elapsed
request time is retained in `.pt/d1/requests.md` and `.pt/d1/requests.jsonl`. Identifiable
member payloads stay in that ignored local evidence rather than in the repository.

| Step | Actual result | Request elapsed |
| --- | --- | --- |
| `GET /health` | `200`, service `ok` | 71.779 ms |
| `GET /ready` | `200`, all three configured checks true | 270.720 ms |
| League status | `200`, connected; published GW2 | 5.414 ms |
| First advice read | `404 NOT_COMPUTED` | 10.529 ms |
| Submit the same selection | `202`, a job identifier and `queued` status | 21.645 ms |
| Poll job | `200` throughout; queued, running, then completed | All 16 polls recorded locally |
| Read after completion | `200`, computed GW4 advice | 26.897 ms |
| Repeat identical read | `200`, exactly the same bytes | 13.210 ms |

The worker's completion log measured 29.936 seconds for this job. These are observations
from one local run while the test suite was also active, not a latency benchmark or capacity
claim. The probe's `submit_to_terminal_seconds` result field includes the verification
reads after terminal polling; use the timestamped exchange and worker log for timing.

The answer is a schema-valid computed plan with solver status `OPTIMAL`, a starting XI,
bench, captain and transfer. Its selected member, rival, strategy, window and source capture
match the request and configured context. The two HTTP responses and the worker-created
cache file are byte-identical; their SHA-256 is
`337745bc252b2b4ea5ad6ef32bd920310dcb69445e6e76dd49a58b20b5dbb3d1`.

Before/after SHA-256 manifests matched for the selected capture's files, the registry, the
matching handoff and every file in this worktree's published site-data tree. This establishes
unchanged bytes for those inspected inputs, not an operating-system read-only mount.
The worker exited normally with code `0` after its one job. The probe then stopped the API;
the API's recorded exit code `1` is that intentional Windows process termination, not a
startup or request failure.

## Findings left unchanged

- **Published week differs from computed week.** League status reports the existing GW2
  membership publication while the advice context and computed answer are GW4. The registry
  members match, so this did not block backend computation. `/ready` accepts the published
  file's existence without checking its freshness. D3 must demonstrate the actual browser
  behavior under this mismatch; this run does not establish it. Publishing current league
  views is an ops/application-lane dependency, not permission to edit that lane's code.
- **Job completion time is inaccurate.** The worker claimed at `13:03:37Z` and logged
  completion at `13:04:07Z`, but the terminal job still returned `updated_at_utc` equal to
  `13:03:37Z`. The worker stamps a round before computing, and the queue reuses that instant
  for its terminal transition. Job state and cache bytes were correct; its terminal
  timestamp must not be used to measure solve duration. This is a D2 follow-up candidate;
  no timestamp fix is included in D1.
- **Source limitations stay visible.** The computed answer retains `data_quality: partial`
  and its reported missing source fields. No substitute input values were supplied by the
  probe to make the request succeed.
- **Documentation paths have moved.** The brief's `docs/backend.md` is now
  `docs/architecture/backend.md`. Its window-one-only descriptions lag the current engine;
  this run only verifies the rival strategy's window-one path.
- **Metrics have a process boundary.** The API metrics response reflects API counters and
  queue depth, while the worker's solve event is in `worker.log`. This run does not establish
  aggregation of worker metrics into the API process or structured per-request logging.

No corrective change was needed to complete this request. The timestamp defect is recorded
for follow-up rather than silently corrected in D1. There was no browser test, frontend
origin change, container build, hosting operation, secret change or deployment. Subsequent
deliveries remain separate from this D1 PR.

## Quality-gate outcome

Ruff lint, Ruff format, strict mypy and both import-linter contracts passed. The installed
`lint-imports` entry point was used because `python -m lint_imports` is unavailable.

The initial full pytest attempt exited with a Windows access error on `.pt/t`, including
during `pytest_sessionfinish`; its individual setup errors could not be classified from
that incomplete report. A fresh full run outside the sandbox, using `.pt/t2`, completed:
**4377 passed, 1 failed, 5 skipped, 9 warnings**. It is a failed full gate, not a green one.

The failure was
`test_horizon_publish.py::test_verified_batch_adds_solver_evidence_without_replacing_the_ledger`.
During fixture setup, `src/squadopt/live/ledger.py` raised `PermissionError: [WinError 5]`
on `os.replace(staging, directory)`. An isolated rerun with a fresh `.pt/t3` passed without
any code change. The exact cause remains unproven; one passing rerun does not erase the
full-suite failure. Investigation of publication in `live/ledger.py` belongs to its owning
lane if a source change is needed. D1 includes no workaround or cross-lane fix.

The skipped tests require an optional Parquet engine, an opt-in container run, or an opt-in
browser run. The warnings are the recorded scikit-learn convergence warnings. Full output,
the focused rerun and exact commands/exit codes remain in `.pt/gates/` and the prepared PR
body. The source, tests and `pyproject.toml` are unchanged from the recorded execution base.

## Local evidence inventory

All paths below are relative to the backend worktree and are ignored scratch evidence:

- `.pt/d1/requests.md` and `requests.jsonl`: every actual HTTP request and response, including
  all polls, request timing and timestamps.
- `.pt/d1/configuration.json`: exact commands, paths, process IDs, origin and environment
  settings used; `.pt/d1/probe.py`: the execution/recording script.
- `.pt/d1/api.log`, `worker.log`, `answer.json`, `result.json` and `store/`: process logs,
  computed response, outcome and the worker's immutable cache/job/spec files.
- `.pt/d1/inputs-before.json` and `inputs-after.json`: input-integrity manifests.
- `.pt/gates/`: complete quality-gate output and exit status, including unsuccessful attempts.

The full local exchange is the D1 evidence document. This repository summary omits the
private capture/member payloads; the raw logs are not a published artifact.
