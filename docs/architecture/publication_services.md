# Installed publication services

The static publishers have application entry points that can be imported from the wheel.
They read explicit paths and return typed results with `output_paths`; they do not parse
arguments, print to the console, contact a data source, execute a season tick or import
`scripts` or `platform`.

| Service | Request | Result |
| --- | --- | --- |
| `application.league_publication.publish_league` | `LeaguePublicationRequest`: capture root/ID, archive, registry, site root, league, optional season/gameweek, handoff, residuals, record root and publication clock | Capture ID, season, gameweek, existing `LeagueViewsReport` and output paths, including the rendered members' private record files when recording is enabled |
| `application.scoreboard.publish_scoreboard` | `ScoreboardPublicationRequest`: capture root/ID, registry, ledger, site root, league, optional season, cohort/picks IDs and clock | Existing scoreboard document, target path, capture/season and coverage counts |
| `application.site_publication.publish_site` | `SitePublicationRequest`: snapshot, ledger, archive, handoff, summary and log roots; site root; optional capture ID, season, clock, horizon manifest and status/league switches | Existing `SiteBuildReport`, the selected capture ID and written output paths |

All paths are supplied by the caller. The services derive no repository root from
`__file__`, and the installed weekly runner must resolve its configured workspace before
constructing a request. Paths returned for immutable advice records are private run
evidence, not additional public site files.

## Preparing and scheduling the member publication

`prepare_league_publication` validates and reads a named capture and registry without
opening the archive, solving, or creating any publication or advice record. It returns
`PreparedLeaguePublication`. The legacy dry run uses this function.
`publish_prepared_league` completes that same prepared request, while `publish_league`
combines both steps for callers that do not need a dry run. Optional typed progress
callbacks let a CLI report the capture before later preparation or publication fails.

The optional mapper remains the existing `MemberMapper` contract. Process creation lives
in `platform.publication_workers.league_mapper`, which returns the ordinary mapper for
one worker or a spawn-based pool for multiple workers. Its initializer receives the
request's capture ID, archive and handoff paths, season and target gameweek. It still
refuses to substitute `render_member` for an arbitrary callable.

Both mapper modes bind the native window executor for three- and five-week primary
searches, unless the caller passes `native_windows=False`: then nothing is bound and
every window search runs on CP-SAT alone, as in a comparison build with
`scripts.build_league_site --cp-sat-windows`. The API advice worker binds the same
executor per request. Its pinned HiGHS 1.15.1 driver runs in a separate interpreter
because the Linux libraries shipped by OR-Tools and highspy cannot be loaded together.
The planner checks the rounded native solution against every exact integer MILP row and
then the original CP-SAT model. Only a proved optimum is accepted: the dual bound HiGHS
reports must lie within half a unit of the witness's exact integer objective, which is
computed from the rounded witness and never read from HiGHS's floating-point objective.
The native attempt is a phase of its own, bounded by the primary's per-phase wall
ceiling, as every phase already is. Unsupported models, failed children and unproved
answers fall back to CP-SAT with the primary's own unchanged wall ceiling and
deterministic budget, so a fallback plans what CP-SAT alone would have planned; a window
whose native attempt and fallback both reach the ceiling can therefore spend two
ceilings on its primary search. A clock-limited native answer does not seed fallback.
One-week solves, hold probes and the deterministic tie-break retain CP-SAT. The model,
strategies and configured ceilings are unchanged.

No published document names the backend: a window document still carries only
`solver_status` and `optimality_gap` from the search. The operator reads it instead.
Each member render collects one outcome per window search (the backend that answered,
the HiGHS version the child reported, and any fallback reason, which includes the tail
of a failed child's standard error). The weekly league stage writes them per member
and window length under `leagues.<id>.window_solvers` in its receipt and as one
`tick.week.league.window_solver` run-log event each; the API worker adds the same rows
as `window_solvers` on the job's terminal log event. The weekly preflight starts the
child once and refuses the week, before any capture, unless it loads highspy 1.15.1.
`scripts.build_league_site` makes the same check before it solves and prints the same rows
per member after the build.

The offline element-to-code translation and `CapturePicksProvider` now live in
`application.capture_entries`, and callers import them from there;
the HTTP context still composes its own backend identity and handoff requirements above
that shared adapter.

This preserves the existing process design: each worker reopens the named capture and
handoff path. It does not promise an atomic byte snapshot of a mutable handoff path across
all workers. Capture checksums and handoff identity checks retain their existing authority;
the enclosing runner owns artifact fingerprinting and coordination.

## Selection, evidence and compatibility

League and scoreboard requests require a concrete capture ID. Their legacy CLI shells
still resolve a missing `--snapshot-id` to the latest live capture before calling the
service. The member publication can additionally name a target gameweek, which both the
parent and worker pass to the same `read_inputs` validator.

The site request also accepts an explicit capture ID. When supplied, both its read-only
status plan and league/provisional-score views use that capture; a newer capture does not
silently replace it. A pinned non-live capture is rejected. Without an explicit ID, the
legacy latest-live and season-tick planning behavior is unchanged. Building the plan does
not execute any suggested capture, decision or settlement action.

`scripts.build_league_site`, `scripts.build_scoreboard` and `scripts.build_site` retain
their existing flags, defaults, progress/error text and exit codes. The old public score
helpers and cohort records are direct re-exports of the installed owners. Script tests
that observed the internal snapshot reader now patch its application owner; they still
invoke the old CLI `main` and assert which capture was read. The old site's schema-only
option and repository schema refresh remain CLI behavior; the installed service already
writes the public schema into its requested output tree.

The league renderer, scoreboard arithmetic, public contracts, projection/solver choices,
and advice replay rules are unchanged by this extraction. Nineteen moved functions/classes
retain their original executable AST, excluding docstrings. A publication that fails late
may already have written public files, as before; callers must record the failure rather
than interpret missing result metadata as proof that no output was written.

## Verification

`tests/unit/test_publication_services.py` exercises shared object identity, preparation
without writes or archive access, one-process versus real two-process byte equality,
private record output paths, pinned scoreboard/site captures, and read-only status
planning. Existing CLI and public-output suites continue to exercise the compatibility
shells and scoring contract.

Local receipts under `.pt/enterprise/publication-services/` record the focused tests,
moved-symbol AST comparison and a wheel import/publication probe in an isolated working
directory. The wheel probe supplies all inputs explicitly and forbids importing the
repository's `scripts` package. These checks use synthetic data; they neither regenerate
the published league nor read production snapshots.
