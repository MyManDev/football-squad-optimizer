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

The offline element-to-code translation and `CapturePicksProvider` now live in
`application.capture_entries`. `platform.capture_context` re-exports the same objects;
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
