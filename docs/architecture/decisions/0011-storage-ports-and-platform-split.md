# ADR 0011: Storage ports, a named data vocabulary and the platform split by deployment unit

- **Status:** accepted by the owner on 2026-10-13. It supersedes the deferral of M6 in
  [ADR 0008](0008-structure-investment.md). It also amends
  [ADR 0010](0010-clean-architecture-rings-and-repository-layout.md): two triggers of its
  deferred moves, and its open questions 1, 2 and 4.
- **Date:** 2026-10-13
- **Decider:** Ertuğrul (repository owner)
- **Related:** [ADR 0005](0005-persistence-boundaries.md), [ADR 0006](0006-backend-hosting.md),
  [ADR 0007](0007-enterprise-transition.md), [ADR 0008](0008-structure-investment.md),
  [ADR 0010](0010-clean-architecture-rings-and-repository-layout.md),
  [dependency rules](../dependency_rules.md), [architecture overview](../../../ARCHITECTURE.md),
  [planner policy chain preregistration](../../research/planner_policy_chain_prereg.md)

## Context

On 2026-10-13 the owner directed that the architecture is fixed directly and that this is now
the first priority. ADR 0010 named the rings, and the overview it added listed thirteen known
violations, each with a remedy. It deferred most remedies to a third phase, behind triggers or
open questions. This record decides those remedies.

The figures below were measured at 8a81c3fd, the `develop` commit that carries ADR 0010. Import
counts come from an AST scan that includes imports inside functions. The Phase 2 branch, which
folds `integration` into `application`, adds one application statement to the first group
(`projection_csv` importing `load_csv` from `data.loaders`), which the storage ratchet counts as
its 122nd edge.

**Storage imports.**

- `application` imports the storage half of `data` in 88 statements across 29 modules, `live`
  in 17 across 9, and `features` in 16 across 4.
- None of them imports the `data` package root.
- 78 of the 121 statements import only pure vocabulary that happens to sit in modules named for
  storage: application 49, live 14, features 15.
- 28 statements import only IO names, and 15 mix the two (all in application).
- The IO collapses into nine concerns:
  - capture reads;
  - archive reads;
  - the club-news fixture file;
  - atomic replace;
  - create-once writes;
  - table write and hash;
  - long-path rendering;
  - the git revision;
  - the ledger store.
- Some of the pure modules are large or central:
  - `src/squadopt/data/sources/fpl_live.py` (2,387 lines) never fetches.
  - `fpl_set_pieces`, `fpl_information` and four club-news parsers read no file.
  - `CapturedSnapshot` and the capture id and fingerprint functions in
    `src/squadopt/data/snapshots.py` are pure.

**Ports.**

- 24 classes are typed `Protocol` ports: 15 in `platform`, 3 in `application`, 1 in `data`, 3
  in the domain (`planning` and `scenarios`) and 2 in the laboratory.
- Of the 15 in `platform`, 7 are seams inside an adapter:
  - `ApiDocument`;
  - the Gemini `Transport` and `Reply`;
  - `MessagesResource` and `CodingClient`;
  - the OpenAI `Transport`;
  - `RuntimeEventSink`.
- The other 8 are use-case ports of the advice backend: `AdviceCacheRepository`,
  `AdviceJobSpecStore`, `JobQueue`, `AdviceContextProvider`, `SwitchInputsProvider`,
  `LeagueDirectory`, `RateLimiter` and `PublishedViewStore`. Their consumers are in `platform`,
  except that `api` takes a `PublishedViewStore` and holds its file adapter.

**platform.**

- 53 modules and `__init__.py` sit in one flat package that serves three ADR 0006 units: the
  API, the worker and operations.
- Import statements of `platform` modules: 104 inside `platform` outside its `__init__.py`, 14
  from 4 `api` modules, 25 from 19 scripts (4 of them in the frozen chain runner), and 306 from
  108 test files.
- `src/squadopt/platform/__init__.py` re-exports 61 names from `api_contract`, `queries`,
  `artifacts`, `context`, `manifest` and `runtime`. So the weekly run, the CLI and the captures
  all load the backend's transport contracts.
- A partition into seven subpackages was tested on the import graph:
  - it has 11 edges between subpackages, all downward and none upward;
  - the API and the worker cannot be separated, because `advice_job_spec -> advice_read`,
    `queue_contracts -> advice_cache`, `_damaged_entry -> advice_observability` and
    `advice_worker -> backend_runtime -> worker_heartbeat` form one cluster.

**ADR 0008's four reasons for deferring M6, measured again.**

1. The 34 path and SHA-256 pins are in the dated record
   `docs/architecture/advice_capacity_20260909.json`. They are history, and no test, script or
   module reads that record.
2. The rewrite surface is now measured (the figures above).
3. The open draft that touches the moved modules is #969. It is sequenced first, and the
   operations move waits for it.
4. The backend has run since 18 September 2026 on the owner's PC behind the `squadopt-api`
   tunnel ([operations inventory](../operations_inventory.md)).

**The decision core and contracts.**

- `planning` and `scenarios` import 19 private names (7 distinct) from `optimization.optimizer`.
- Across `src`, 39 private names cross a package boundary.
- 9 test files monkeypatch those names on the modules that consume them.
- `contracts` reads and writes files:
  - `league_list.py` has `LEAGUE_LIST_FILE` and `read_league_list`;
  - `league_tree.py` has four functions that read or write files, the ones
    `tests/architecture/test_core_file_io.py` allowlists, and three more that list the
    directory tree. These seven are imported by 7 modules and scripts and by 7 test files.
- `evaluation/component_handoff.py` reads the Phase C manifest and tables. Only 12 research
  scripts call its reader.
- 8 modules build a `docs/contracts` path relative to the working directory.
- `application/advice_record.py` reaches `git` through `src/squadopt/data/source_revision.py`.
  That module derives `PACKAGE_ROOT` from its own file, so it never moves.
- `live/ledger.py` (1,212 lines) is the only `live` module that imports `os`, `shutil` and
  `secrets`. Its record primitives are also used by `application/advice_record.py`,
  `platform/capture_measurement.py` and `platform/benchmark_capture.py`.

**The planner policy chain.**

- Release `site-2026-27-gw06-fix17` carried the frozen commit's binding source and a different
  planner source.
- `develop` now differs from f843d24b in 5 of the 8 binding files and in 8 planner files.
- Under rule 3, every release from GW7 on therefore reads "release differed" on both sources,
  whatever this record does.
- The bound runner `scripts/measure_planner_policy_chain.py` and the scorer
  `scripts/score_planner_policy_chain.py` are never edited. They import four `platform`
  modules, and names from `data.snapshots`, `data.atomic` and `data.sources.fpl_live`, by
  today's paths.

**Constraints.**

- The weekly publish refuses when `origin/develop` no longer holds the run's revision.
- `scripts/release/restart_backend.ps1` compares `src`, `scripts` and `docs/contracts` with
  the live site release before it restarts the backend.
- A full rehearsal must pass on the final `develop` before each publish.
- The editable install in `.venv` points at the main checkout. So gates run in a worktree need
  `PYTHONPATH=<worktree>/src`.

## Decision

**1. Storage ports are built now (answers ADR 0010 question 4, first part).**

- **Where a port lives.** A port is declared in the innermost ring that consumes it:
  - `CaptureReader` goes in `squadopt.data.capture` (R1). Both `live` and `application`
    consume it, and it names `CapturedSnapshot`. `contracts` imports nothing from `squadopt`
    outside itself, so it cannot hold the port.
  - `LedgerStore` goes in `squadopt.live.ports` (R2).
  - The rest go in `squadopt.application.ports`, with one module per port group and no barrel:
    - `archive`: `ArchiveReader`;
    - `publication`: `PublicationFiles`, `PublicationIdentity`;
    - `artifacts`: `ArtifactFiles`;
    - `club_news`: `ClubNewsFixture`, `ClubNewsFixtureOpener`, `ClubNewsSources`;
    - `rotation_evidence`: `RotationEvidenceReader`;
    - `advice_records`: `AdviceRecordFiles`;
    - `revision`: `RevisionReader`.
  - `ClubNewsProvider` moves unchanged to `squadopt.data.payloads.club_news`.
- **What a port looks like.** Each port mirrors the existing `data` function one for one, and
  is keyed by the root `Path` that requests already carry. Request types, command-line flags
  and the error messages that name a root therefore stay byte-identical. Issue #1010's
  direction (a bucket synced to local files) keeps the file adapters as the production
  adapters.
- **How use cases receive ports.** Use cases take ports as required keyword-only arguments.
  Three alternatives are refused:
  - a default value, because it is an import of the adapter;
  - an import inside a function, because it is still an edge;
  - a registry, because it hides the dependency behind the run-time load of
    `src/squadopt/data/__init__.py`.
- **Adapters.** They live in `squadopt.platform.storage`, one module per group.
  - Each is a stateless frozen slots dataclass, exported as a module-level singleton annotated
    with its Protocol. mypy then proves conformance, and the singletons pickle by reference
    across the league stage's process pool.
  - They call the `data` functions unchanged, or hold code moved verbatim and run in the
    original order. Errors keep their precedence and their text.
- **Composition roots wire the adapters.** These are `squadopt.platform.weekly_operations`, the
  `CliServices` object of `squadopt.platform.cli`, `squadopt.platform.publication_workers`, and
  the scripts that call a changed use case.
- **No port for the clock or for handoff writing.** The clock stays the existing `now` and
  `generated_at_utc` parameters plus `CliServices.clock`. Handoff writing keeps its existing
  `writer` injection.
- **End state.** When `application`, `live` and `features` reach zero storage imports, they
  become sources of the storage contract, and the Phase 2 ratchet is deleted.

**2. `data` stays one package, and its vocabulary half gets named modules (answers question 4,
second part).**

- **The new modules.**
  - `squadopt.data.capture` holds the capture vocabulary and `CaptureReader`.
  - `squadopt.data.canonical` holds `document_bytes`, `WRITTEN`, `REPLAY`, `sha256_of_bytes`,
    `EXPORT_LINE_TERMINATOR` and `is_source_revision`.
  - `squadopt.data.payloads` holds the FPL and club-news parsers and the captured half of
    `football_history`, with today's basenames.
  - `PriceUnit` moves into `cleaning`.
- **Contract sources.** Each vocabulary module becomes a source of the storage contract, as do
  `cleaning`, `claim_identity` and `cohorts`.
- **The storage half** keeps its module names. It holds acquisition, file readers, writers and
  the re-export shims.
- **Not changed here.** The run-time load of `src/squadopt/data/__init__.py` is unchanged; the
  data owner decides it later.
- **Ownership and fallback.** The data owner reviews each move. If he declines, the fallback is
  to name the IO modules in the forbidden lists and leave the files in place.

**3. `platform` splits by deployment unit (answers question 2, and supersedes ADR 0008's
deferral of M6).**

- **Seven subpackages**, with module basenames unchanged:
  - `storage` (shared durable-state primitives and the storage adapters);
  - `runs` (run identity, provenance and the stage journal);
  - `capture` (FPL network captures);
  - `club_news` (club pages, the official injury capture and the model clients);
  - `football` (football input artifacts, prepared by operators and read by the backend);
  - `backend` (the API and worker cluster);
  - `operations` (the CLI, the weekly run and the publication workers).
- **A new layers contract** keeps the units in order. It is named "Platform deployment units
  import only the shared adapters below them", with `containers = ["squadopt.platform"]`.
  - Layer order: `operations | backend`, then `football`, `club_news`, `capture`, `runs`,
    `storage`.
  - It is exhaustive, with the flat alias names ignored.
  - The top-level layered contract is unchanged.
- **Package files.** Each subpackage's `__init__.py` is a docstring only. The 61 root re-exports
  are removed one release after the moves that carry them.
- **Why the splits are drawn there.** The API and the worker stay in one subpackage because of
  the cluster above. `weekly_journal` sits in `runs` because the backend-read football bundle
  imports it.

**4. `contracts` and the decision core hold no file IO.**

- **The league list** (`LEAGUE_LIST_FILE`, `read_league_list`) moves to
  `squadopt.platform.operations.league_list`.
- **The league directory's seven IO functions** move to `squadopt.application.league_directory`.
  `contracts` keeps two pure functions carved from them, `parse_league_directory` and
  `render_league_directory`.
- **The Phase C file reader** moves to `squadopt.preflight.component_handoff`. `evaluation`
  keeps the pure checks and the assembly. The dependency rules then read "`preflight` imports
  `data` and `evaluation`".
- **No re-export is possible here.** `contracts` is the lowest layer, and `evaluation` may not
  re-export from the laboratory. So every caller is repointed in the same pull request.
- **Trigger amended.** ADR 0010's trigger for the league list, "after issue #981", becomes
  "before #981 step 6 opens, announced on #981".

**5. A public CP-SAT driver, `squadopt.optimization.cpsat`.**

- **Bodies moved.** The driver's bodies move verbatim. `add_tiebreak_objective` moves to
  `optimization.decisions` and `empty_result` to `optimization.models`.
- **Test seams kept.** Consumers bind the public names to their existing module-level private
  names, so every test monkeypatch seam keeps working.
- **Names that stay in `optimization.optimizer`.**
  - It keeps re-exporting `configure_solver` and the three constants.
  - `wall_clock_stopped_the_search` stays defined there, because a frozen pre-registration
    names it in that module, the test of that protocol reads it there, and
    `tests/unit/test_optimizer.py` imports it from there.
- **Trigger amended.** ADR 0010's trigger "after #969 merges, on measured gain" becomes "before
  the GW7 freeze". The gain is measured: 19 private imports go to 0.

**6. One resolver for schema paths, `squadopt.contracts.schema_paths`.**

- `contract_schema_path(contract_version)` returns today's relative path. So every write
  default and every test read is unchanged.
- Anchoring the path to the repository root would change behaviour, so it is a separate
  decision for the owner.

**7. No Protocol moves on its own.**

- The 7 seams inside adapters stay in R4 by design.
- The 8 use-case ports of the advice backend move into `application`, together with the read
  and submit use cases that consume them, if #988 keeps the backend. If #988 retires it, they
  are deleted with it.
- The overview's row on ports is restated as 8 use-case ports, not 15.

**8. Shim policy.** This refines dependency rule 2.

- **Permanent.** These operator entry points keep working forever:
  - `python -m squadopt.platform.weekly_operations`;
  - `python -m squadopt.platform.advice_worker`;
  - `squadopt.platform.cli:main`, where the console script string in `pyproject.toml` stays
    as it is;
  - `advice_load`, `backup_recovery`, `benchmark_capture` and `capture_measurement`;
  - `squadopt.api.runtime:build_app`, which does not move;
  - `scripts/*.ps1`, `scripts/release/*` and the football build and bundle scripts, with their
    paths and flags.

  Each moved `platform` entry keeps a file at its old path that runs `main` only as
  `__main__`, and that aliases itself in `sys.modules` only under its own dotted name. A spawn
  child that runs the alias as `__mp_main__` is then left alone.
  `scripts/build_projection_handoff.py` keeps its historical `build()` signature.
- **Frozen until the planner chain's final reading after GW38.** These names stay until the
  runner and the scorer retire, the way #1080 retired concluded runners:
  - the `platform` modules `advice_switches`, `capture_context`, `football_bundle` and
    `football_minute_basis`;
  - `squadopt.data.snapshots.CapturedSnapshot`;
  - `squadopt.data.atomic.document_bytes`;
  - the `data.sources.fpl_live` names that the runner and the scorer import:
    `BOOTSTRAP_PAYLOAD`, `FPL_LIVE_SOURCE`, `gameweek_deadlines`, `live_event_outcomes`,
    `live_payload`, `player_snapshot` and `scored_gameweeks`.

  This exception to rule 2 is written into the dependency rules.
- **One release.** Every other moved module and name keeps a re-export until the first pull
  request after the next `site-*` release that carries the move.
  - Moved `platform` modules are `sys.modules` aliases, because tests use private names and
    monkeypatch module attributes.
  - Moved `data` names are explicit `X as X` re-exports, because mypy runs strict. A test
    proves each one is the same object at both paths.
  - No test may monkeypatch a shim module.
- **None where a rule forbids the edge.** `application`, `live` and `features` never re-export
  from `platform`. `contracts` never re-exports upward, and `evaluation` never re-exports from
  the laboratory. Callers are repointed in the same pull request: rule 1 outranks rule 2, as
  for `application.mode_selection`.
- **Records.** No record or frozen evidence moves. Path and SHA pins inside dated records are
  history.

**9. Merge discipline.**

- Nothing merges between 24 hours before a gameweek deadline and 24 hours after it. Nothing
  merges while a Tuesday settle or a publish run is in progress.
- A full rehearsal passes on the final `develop` before each publish.
- Pull requests merge one at a time through the merge queue. Each one lowers the ratchets it
  affects in the same change.
- Every change to `src` reaches the backend only at a release, after the owner restarts the
  backend from a plain shell with the release tag.

**Answers to ADR 0010's other open questions.**

- Question 1 (the scripts regroup): no, not this season. It changes navigation only, costs
  about 213 import edits, and would edit runner paths that pending readings hash.
- Question 3 (version 2.0.0) stays open.

## Consequences

- Of the thirteen rows the overview listed with ADR 0010, nine close, as follows.
  - Already closed by Phase 2:
    - the laboratory modules in `application`;
    - `integration` as a layer.
  - Closed by this record's moves:
    - the CP-SAT driver;
    - the decision core reading files;
    - `contracts` file IO;
    - the three vocabulary modules;
    - the process started through `data`;
    - the `platform` roles;
    - the storage imports, which become an enforced contract.
- Reduced, not closed:
  - The `docs/contracts` path rule: one resolver, still relative.
  - The ports row: 8 use-case ports, waiting on #988.
  - The `data` two-rings row: the vocabulary half is named and enforced, and the run-time
    load stays.
- Unchanged:
  - The scripts row.
- Two rows are held by shrink-only tests:
  - Private names imported across packages, a new row. 13 remain, all in the laboratory.
  - Direct file IO in `application`, `live` and `features`, the row Phase 2 added without a
    check. A zero storage-import count does not mean R3 does no IO. The publication tree
    writers wait for a publication-writing port in a later record.
- Test churn:
  - about 306 import statements in 108 test files for `platform`;
  - about 20 monkeypatch seams on `application` attributes, repointed to fake ports, which fail
    loudly (`AttributeError`) if missed;
  - a codemod over about 150 to 200 files when the `data` shims go.
- Operations:
  - Each release that carries a `platform` move needs the owner to restart the backend.
  - A weekly run started before a move cannot resume after it, because `package_sha256`
    changes, as with any code change.
- Review load: the data owner reviews the `data`, club-news, `planning`, `contracts` and
  ledger changes.

## Rejected options

- **A registry or service locator** filled at import time. It hides the dependency behind the
  run-time load of `src/squadopt/data/__init__.py`.
- **Imports inside use-case functions.** They are still an edge.
- **Stores carried on requests now.** About 20 scripts and many tests build the requests, and
  the roots appear in error messages.
- **A new top-level storage package.** `platform.storage` needs no ring row and no new layer.
- **A separate vocabulary package for `data`.** It would rename about 150 import sites twice.
- **Ledger primitives in a new `data` storage module as an interim step.** It adds a storage
  edge from `live` that the edge ratchet refuses.
- **A `run_phase()` helper in the CP-SAT driver.** It would bypass the private names that
  tests patch.
- **Separate subpackages for the API and the worker.** They form one import cluster.
- **A subpackage named `cli`.** It cannot coexist with the permanent `platform/cli.py`.
- **Star re-exports for `platform` shims.** They break private names and monkeypatching.
- **Anchoring schema paths on `__file__`.** It breaks the non-editable container install and
  changes where files are written.
- **Moving a Protocol without its consumers.**
- **Pointing `evaluation/benchmarks.py` at the driver's `solve`.** It adds `model.validate()`
  and changes the exception type.
- **Splitting the largest modules before GW7.**
