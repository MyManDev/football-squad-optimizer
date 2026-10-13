# Architecture decision records

Each record states one decision, the context and measurements it rested on, the options it
rejected and its consequences. A record is never renumbered or renamed: other documents cite
the files by path, and `tests/architecture/test_measurements_index.py` reads ADR 0003 by its
path. A later decision amends or supersedes an earlier one in a new record, which says so in
its header.

| ADR | Title | Date | Status | Amended by |
| --- | --- | --- | --- | --- |
| [0001](0001-modular-monolith.md) | One layered package, enforced by a linter | 2026-08-18 | Accepted | None |
| [0002](0002-contract-versioning.md) | Where contract versions and fingerprints live | 2026-08-18 | Accepted | None |
| [0003](0003-measurement-artifacts.md) | What a measurement artifact is, and where it lives | 2026-08-18 | Accepted | None |
| [0004](0004-cloudflare-pages-deployment.md) | Publish tested static artifacts with Cloudflare Pages | 2026-08-20 | Accepted | None |
| [0005](0005-persistence-boundaries.md) | Separate transactional metadata from analytical artifacts | 2026-08-20 | Accepted | None |
| [0006](0006-backend-hosting.md) | Host the advice backend beside Pages, not inside it | 2026-08-27 | Accepted | Amended in place on 2026-08-27, after the platform owner's review |
| [0007](0007-enterprise-transition.md) | Move the operational scripts into the installed package, in one change | 2026-09-10 | Accepted | None |
| [0008](0008-structure-investment.md) | Spend the structure budget on repetition and boundaries, not on renames | 2026-09-15 | Accepted | [0011](0011-storage-ports-and-platform-split.md) supersedes the deferral of M6, the `platform` split |
| [0009](0009-advice-backend-hosting-options.md) | Where the advice backend runs, five options compared for the owner's decision | 2026-09-25 | Proposed | None |
| [0010](0010-clean-architecture-rings-and-repository-layout.md) | Clean-architecture rings and the repository layout | 2026-10-13 | Accepted (owner, 2026-10-13) | [0011](0011-storage-ports-and-platform-split.md) amends two triggers of the deferred moves and answers open questions 1, 2 and 4 |
| [0011](0011-storage-ports-and-platform-split.md) | Storage ports, a named data vocabulary and the platform split by deployment unit | 2026-10-13 | Accepted (owner, 2026-10-13) | None |

ADR 0004's own revisit condition led to ADR 0006, which keeps the static site and adds the
backend beside it. ADR 0010 builds on ADRs 0001 and 0008 and leaves their decisions standing.
ADR 0011 decides the remedies ADR 0010 deferred, and is the record ADR 0010 said the `platform`
split needs.

## Decided without an ADR yet

These decisions are in force and recorded elsewhere. Each is a candidate for a retrospective
record.

| Decision | Date | Where it is recorded |
| --- | --- | --- |
| `develop` merges through a GitHub merge queue; the required checks also run on the `merge_group` event | 2026-09-26 | Pull request #867, `.github/workflows/ci.yml`, [branching](../branching.md) and the [deployment runbook](../../deployment_runbook.md) |
| Device-first computation and listed multi-league support: the member's browser solves the plan, and the leagues come from `config/leagues.json` | 2026-10-05 | Issues #978 and #981, the [device-plan contract](../../contracts/league_device_plan_v1.md) |

Product and operations decisions that are not architectural, such as the weekly operating
schedule and the strategy names, are kept in [docs/decisions.md](../../decisions.md).

## Adding a record

Take the next free number, name the file `NNNN-short-title.md`, and start it with the same
header fields as the records above: status, date, decider and related records. A record is
**proposed** until the decider accepts it. Add its row to this table in the same pull request.
