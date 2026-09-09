# Enterprise transition acceptance — 10 September 2026

Branch: `codex/enterprise-software-transition`. This records local acceptance and
remaining limitations; it does not claim a production deployment or a green full suite.

## Completed checks

| Check | Observed result |
| --- | --- |
| Whole Python static analysis | Ruff lint/format and strict mypy passed; 258 source files |
| Layer contracts | 258 files, 1,075 dependencies; both contracts kept, zero exemptions |
| Web unit suite | 490 passed, 2 skipped; the opt-in publication contract also passed separately |
| Web release checks | Production build, asset/deployment checks, size budget and formatting passed |
| Browser suite | 68/70 initially passed; two obsolete wrong-path error expectations corrected, then all 13 affected cases passed |
| Actual browser/API/worker/cache and Python–TypeScript publication | 2 passed in 32.20 seconds on the final package source |
| Linux image and Compose acceptance | 4 passed in 48.02 seconds, including persistence and missing-mount refusal |
| Capacity | 6 configurations / 18 scenarios passed in 143.67 seconds; see [measurements](advice_capacity.md) |
| Installed weekly workflow | 239 focused tests and isolated wheel run/resume/status passed |
| Full Python suite | 4,755 passed, 19 failed, 13 skipped, 9 warnings in 255.88 seconds; classification below |

The tested local image `squadopt-backend:enterprise-20260910` is Linux/amd64,
193,583,356 bytes, ID
`sha256:a0d0c77887821a34434bcdd7a626a2c68476d1404247bf3669c41daf7a18de42`.
Its declared repository revision is `baf60e6fd13559f6f392e9ebb0200afd8e9c9a7b`.
Subsequent compatibility corrections affect repository script exports, test assertions
and constraints, not the installed package source tested in that image. This is a local
image identity, not evidence of a registry release or remote rollout.

## Full-suite findings

- Eleven Phase E failures exposed missing legacy handoff script constants used by an
  actual runtime caller. Restored exports from the installed owner; all 47 tests in the
  producer/live modules passed, including a compatibility regression.
- Two advice tests expected obsolete rejection text. Updated the assertions to the
  shared capability contract; invalid requests are still rejected. Added the missing
  `psutil==7.2.2` constraints pin identified by a third test. The three affected modules
  passed all 54 tests.
- Three Windows directory-rename permission failures remain recorded: ledger fixture
  setup in `test_build_site_cli` and `test_horizon_publish`, and immutable record
  publication in `test_advice_record`. No retries, workaround, permission changes or
  edits to those writers were made in response to this run.
- Two failures use Windows destination paths of 263 and 262 characters: retained
  handoff creation in the clean-checkout weekly resume test, and backup creation in
  the domain recovery test. With unchanged source and tests, both passed in 5.29 seconds
  using the shorter `.pt/lp1` temporary root. Independent file-create and hard-link
  probes in the original existing parent passed at 259 characters and failed at 260,
  262 and 263, confirming the host's path-length limit. No registry or extended-path
  behavior was changed. Use short Windows workspace, test and backup roots; long-path
  support is not established by this acceptance.

The 13 full-suite skips are one unavailable Parquet engine, six opt-in capacity cases,
four opt-in container cases, and the browser/backend and publication-contract cases.
All twelve opt-in cases passed in their separate acceptance runs. Nine warnings are
Gaussian-process convergence warnings from the existing terminal-value study.

Local raw logs and detailed failure classification remain under `.pt/enterprise/`.
They are development evidence, not private production backups. Remote CI remains a
separate merge gate; no failed test has been removed or marked xfail for this transition.

## Remote CI follow-up

[PR #456](https://github.com/MyManDev/football-squad-optimizer/pull/456) targets develop.
The first CI run passed all 70 Playwright cases and 491 web unit tests (one skipped),
along with the web build and release checks. Container and browser/backend fixtures
then exposed a clean-checkout setup error: the parent `.pt` directory did not exist
for the explicit pytest base directory. Both workflow steps now create that parent
before pytest. Failure artifacts explicitly include files under the named hidden
scratch directories. The first failed CI result remains evidence; a subsequent run
must establish acceptance of this workflow correction.

Both full Linux Python gates in that first run passed: Python 3.11 completed its gate
in 9m31s (4,778 passed, 14 skipped); Python 3.13 completed its gate in 10m6s. No Python
source was changed by the workflow-directory or subsequent link-contrast correction.

## Final user-journey E2E

The existing real-browser test was extended to begin at the entry page: unsupported
league 123 is rejected without a fetch; entering 352490 loads the actual publisher's
member list; selecting "Bu benim" stores the viewer and opens that member. The same
session submits advice, observes HTTP 202 and worker completion, renders the result,
then reloads and receives the cached HTTP 200 answer. No HTTP route is mocked in this
test; captures are synthetic and API/worker are separate real processes.

The first expanded run found insufficient light-theme contrast on the selected-member
"Üyeyi değiştir" link (4.33:1). Its scoped style now uses the existing text color token.
The corrected journey and axe check passed in 22.54 seconds. This adds no product
feature or architectural layer. Rival and multi-week choices remain separately tested
in UI, API and domain checks; this combined browser solve covers pure points, one week.
Restore/resume drills are local and synthetic, not acceptance of a restored remote host.

## Unfulfilled operational and research prerequisites

No independent backup destination, live backend host or running weekly scheduler was
verified. Configurable tools and local drills do not establish recovery objectives or
production acceptance. See [the inventory](operations_inventory.md).

Ibo's evidence capture/replay delivery is still a separate integration prerequisite.
Prospective Top100 comparisons require future captured decisions and outcomes.
Scientific promotion gates remain in force; no experimental model was activated.
