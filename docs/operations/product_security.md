# Product security workstream

Review started 18 October 2026 against `origin/develop` at `1cbfedbf5`. The owner's
direction is to pause research and focus on frontend and use. This workstream owns the
security of the product's public inputs, publication and operational data; frontend
implementation stays with the existing frontend work. It does not change a model,
solver, scientific gate or published player forecast.

## Why this work now

The evidence supports moving this contributor's time to product work:

- The [continuation diagnostic](../research/continuation_diagnostic.md) found that the
  ANN did not outperform the training mean, and the archive omits state needed for a
  learned policy.
- [Rank-conditional shrinkage](../research/rank_conditional_shrinkage.md) was not certified:
  the primary correction lost 0.847 points per gameweek on 176 paired development folds.
- The [mean-reversion discount](../research/mean_reversion_discount.md) was not certified:
  its primary arm lost 0.56 points per gameweek, with an interval spanning zero.
- The [team-match sampler](../research/team_match_block_sampler.md) still failed S2.
- There are positive results too: the
  [GBM comparison](../research/phase_c_gradient_boosting_comparison.md) prefers its candidate,
  and the [current HiGHS comparison](../research/window_solver_highs_current.md) supports a
  server-switch proposal. Neither record itself changes the live defaults.

These records do not prove that further research can never help. They support the current
decision to pause it rather than opening another learning or optimization project.

## Boundary and existing protections

The browser and arbitrary HTTP clients are untrusted. Public submissions cross the API
boundary into a moderated SQLite inbox or the advice queue. Workers and publication commands
consume captured inputs and write operational state and public JSON. Release workflows cross
the boundary from repository content and build dependencies to the member website.

Existing protections matter: explicit CORS origins, bounded POST bodies, advice request and
open-job quotas, server-side validation, pending-only comments, host-only moderation,
parameterized SQL, daily HMAC visitor digests, and non-root container execution. Public source
links are stored without fetching. Advice already groups native IPv6 clients by /64.
The Pages workflow already separates CI from deployment credentials, qualifies same-repository
previews, runs trusted deployment tooling and rejects executable or malformed site artifacts.
The release audit should verify these boundaries and their regression coverage, not duplicate
the existing deployment pipeline.

The [backend endpoint inventory](advice_backend_endpoints.md) records an earlier retirement
proposal. The owner's decision of 19 October on issue #988 keeps the backend on the VM and
sets that proposal aside. These fixes apply to its current public boundary. The weekly
publication and distributed browser assets are also in scope for any later security review.

## First slice: contribution boundary

Local regression tests use synthetic rosters and isolated databases, with no requests to
production. The initial focused run reproduced eight failing cases: three malformed text
fields, two overflowing player ids, two address-family quota bypasses and a case-sensitive
media-type rejection. An ordinary nested-body case already returned 422. Coverage also
includes nesting beyond the decoder's recursion limit.

| Finding | Consequence before the fix | Change and acceptance |
| --- | --- | --- |
| Native IPv6 and mapped IPv4 addresses were hashed as distinct visitors | One visitor could rotate addresses inside a /64 or use alternate forms to exceed the three-per-hour quota; the global cap of 50 still bounded insertion | Reuse the advice address bucketing at the HTTP boundary. Three submissions succeed; the fourth equivalent address returns 429. A different subnet/address retains its own allowance. Forged forwarded headers grant no allowance. |
| JSON can decode unpaired Unicode surrogates | Each of author, body and source could reach SQLite and produce HTTP 500 plus an exception log | Require UTF-8 encodable text before storage. Invalid strings return 422 without opening the inbox. Turkish text and supplementary Unicode still succeed. |
| The read route had no upper bound on `player_id` | Integers outside SQLite's signed 64-bit range caused HTTP 500 and opened the database | Validate the storage range at the HTTP boundary. Oversized values return 422 without opening the inbox. |
| The decoder's recursion failure was not caught | Extremely nested JSON could escape the normal invalid-body response despite fitting in the byte limit | Map `RecursionError` to the existing 422 response. A subsequent health request succeeds and the inbox remains unopened. |

The same slice accepts case-insensitive `application/json` media types, matching the advice
route. The byte limit, field limits, moderation requirement and response envelopes stay as
documented in [contributions](../contributions.md).

Implementation: [contribution routes](../../src/squadopt/api/contributions.py).
Regression coverage: [contribution tests](../../tests/unit/test_contributions.py).

## Next slices, in priority order

These are scoped follow-up investigations, not claims of verified vulnerabilities.

| Priority | Slice and owned paths | Reviewable deliverable and completion condition |
| --- | --- | --- |
| 1 | Dependency and release supply chain: `.github/`, `constraints.txt`, `pyproject.toml`, `web/package-lock.json`, `Dockerfile` | Inventory direct/transitive runtime and build dependencies, run advisory checks against the actual locks, and review secret permissions and untrusted PR execution. Separate confirmed advisories from update suggestions; gate on actionable findings with a documented exception process. Existing Dependabot config currently updates Actions only. Coordinate lock changes with the frontend owner. |
| 2 | Publication privacy and provenance: `platform/operations`, publication commands and release packaging | Trace every private input to the public JSON/artifact allowlist, and demonstrate that secrets, raw visitor identity and private runtime paths cannot be packaged. Add adversarial fixtures where a concrete missing guard is found. Verify the immutable tag/artifact and rollback path using synthetic inputs. |
| 3 | Operational data recovery: backup commands, SQLite inbox and deployment mounts | Verify what backs up captures, ledger and the inbox; exercise a consistent SQLite backup and restore with active writes in an isolated environment. State the measured recovery result and any missing production configuration. Existing Git/CI artifacts are not evidence of private-data recovery. |
| 4 | Remaining public API exposure, while it is served: API runtime, proxy launchers and deployment ingress | Verify actual trusted proxy peers, public route/metrics exposure, size/time/concurrency limits and quota behavior across restarts/replicas. Keep application and edge limits explicit; test with a local deployment. Avoid expanding the retiring backend. |

The table retains the security follow-ups identified on 18 October. At the owner's backlog
cleanup on 21 October, new work planning is deferred until the existing work is closed.
No production deployment, dependency update, scheduled task or hosting change is performed
by this first slice.

## Local verification

Ruff lint and format pass across the repository, strict mypy passes on 434 source/operator
files, and all 11 import contracts pass. The focused repeat passed 48 tests: contributions,
documentation reachability and the file-operation cases below.

The first full parallel run reported 14,175 passes, 33 skips and six failures. Linking this
guide made `docs/contributions.md` reachable, so its frozen unreachable-document exception
and the pinned list size were reduced as the architecture test requires. The other five
failures concerned Windows file access and long temporary paths; all passed in the focused
repeat under a fresh short `C:/tmp/` directory, without changing their product code or tests.

The final parallel run uses a fresh short base directory, `-n auto --dist loadscope`,
`PYTEST_XDIST_AUTO_NUM_WORKERS=8`, and `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS` and
`MKL_NUM_THREADS` set to 1. These are local verification settings, not application defaults.

Final full result: **14,181 passed, 33 skipped, zero failures** in 766.76 seconds. Skips
include historical-capture-specific fixtures, optional dependencies and opt-in browser,
capacity and container acceptance. The remaining warnings are the existing history date
parsing and Gaussian-process convergence warnings in unrelated tests.
