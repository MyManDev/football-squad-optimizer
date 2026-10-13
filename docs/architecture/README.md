# Architecture agreements

The documents in this folder are the working agreements of the repository: how the code is
layered, who approves what, how a change reaches `develop` and production, and where each
runtime boundary sits. The [architecture overview](../../ARCHITECTURE.md) at the repository root
is the summary; the [decision records](decisions/README.md) explain why.

A document marked in the last column is read by a test, so a change to its wording can fail
the build. The test named there says what it holds. Every Markdown file in the repository is
also read by `tests/architecture/test_markdown_links.py`, every document under `docs/` by
`tests/architecture/test_documentation_paths.py`, and the links of every document reached from
the documentation guide by `tests/architecture/test_docs_reachable.py`; those three are not
repeated below.

## Structure

| Document | What it settles | Read by a test |
| --- | --- | --- |
| [System map](system_map.md) | The package boundaries, the advice request path, publication and recovery | |
| [Dependency rules](dependency_rules.md) | The import order, the laboratory boundary and the rules for changing either | `tests/architecture/test_architecture_rings.py` holds the contract list in its Verification section |
| [Solver boundaries](solver_boundaries.md) | The squad and lineup invariants the live squad and transfer paths share | |
| [Platform and runtime boundary](platform_runtime.md) | How the engine becomes a runtime without infrastructure leaking into it | Its removal note is an allowance in `tests/architecture/test_documentation_paths.py` |
| [Decision records](decisions/README.md) | Why the structure is what it is | ADR 0003 is read by `tests/architecture/test_measurements_index.py` |

## Working agreements

| Document | What it settles | Read by a test |
| --- | --- | --- |
| [Ownership](ownership.md) | Who approves a change in each zone, the shared boundaries and the live-path freeze | |
| [Branching and protection](branching.md) | The trunk, branch protection, the gates, tag namespaces and production deploys | `tests/architecture/test_operations_docs_match_the_workflows.py` holds its production step names |
| [PR discipline](pr_discipline.md) | How a change is scoped and reviewed, and the replay check on the live path | `tests/architecture/test_mypy_file_set_is_described.py` holds its list of type-checked scripts |
| [Development workflow](development_workflow.md) | The baseline of 9 September 2026 and how archived work is recovered | |

## Runtime boundaries

| Document | What it settles | Read by a test |
| --- | --- | --- |
| [Backend HTTP boundary](backend.md) | The versioned HTTP surface over the application contracts | |
| [Advice transport boundaries](advice_boundaries.md) | Which advice request combinations exist and who owns the rule | |
| [Queue recovery](queue_recovery.md) | The queue adapter interface, attempt ownership and recovery | |
| [Publication services](publication_services.md) | The installed static publishers and their typed results | |
| [Installed weekly operations](weekly_operations.md) | The journaled weekly runner and how a run resumes | |
| [Member page boundaries](member_page_boundaries.md) | How the member page separates publication reads, advice state and rendering | `web/src/features/league/queries.test.tsx` holds its `queries.ts` row |

## Operations and recovery

| Document | What it settles | Read by a test |
| --- | --- | --- |
| [Operations inventory](operations_inventory.md) | The inspected hosting configuration and repository variables | `tests/architecture/test_operations_docs_match_the_workflows.py` holds its variables row |
| [Backup and recovery](backup_recovery.md) | Private backups, manifests, trusted receipts and restore verification | |
| [Advice capacity](advice_capacity.md) | The local synthetic acceptance of the advice path | Its record, `advice_capacity_20260909.json`, has a row in the measurements index |

## Dated records

These describe a past transition and are kept as written.

| Document | What it records |
| --- | --- |
| [Archive integration](archive_integration.md) | The archived fixes compared with the published baseline on 2026-09-09 |
| [Evidence validation](evidence_validation.md) | The bounded validation correction of 2026-09-09 |
| [Enterprise developer handoff](enterprise_developer_handoff.md) | The developer handoff of 2026-09-10, in Turkish; the decision is ADR 0007 |

New agreements belong in this folder, with a row in one of the tables above. A decision with
alternatives belongs in a new decision record instead.
