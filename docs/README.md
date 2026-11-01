# Documentation

This folder holds the product, operations, architecture and research documentation, the
versioned public contracts, and the committed measurement records. It is part of the build
surface: tests read some documents, runners write records here, and some paths are embedded in
generated files ([ADR 0003](architecture/decisions/0003-measurement-artifacts.md)). For the
shape of the system, start with the [architecture overview](../ARCHITECTURE.md); for terms, the
[glossary](glossary.md).

## Where to start, by reader

| Reader | Start here | Then |
| --- | --- | --- |
| Operator running the weekly publication or the backend | [Operations guide](operations/README.md) | [Weekly runbook](weekly_runbook.md), [deployment runbook](deployment_runbook.md), [backend runbook](backend_runbook.md), [backend free hosting](backend_free_hosting.md), [rebuilding the production machine](rebuild_production.md) |
| Developer changing code | [Architecture overview](../ARCHITECTURE.md) and [contributing](../CONTRIBUTING.md) | [Architecture agreements](architecture/README.md), [decision records](architecture/decisions/README.md), [script catalogue](../scripts/README.md), [test guide](../tests/README.md), [web guide](../web/README.md) |
| Researcher measuring a model or policy | [Research guide](research/README.md) | [Measurements index](measurements_index.md), [prediction research agenda](prediction_research_agenda.md), [experimentation specification](experimentation_spec.md) |
| Consumer of a published document or the API | [Contract directory](contracts/) | [Data contract](data_contract.md), [data dictionary](data_dictionary.md), [backend HTTP boundary](architecture/backend.md) |
| Reader of reports and decisions | [Product guide](product/README.md) and [roadmap](product/roadmap.md) | [Measurements index](measurements_index.md), [season ledger](season_ledger_2026-27.md), [product and operations decisions](decisions.md) |

## Folders

| Folder | Holds |
| --- | --- |
| [architecture/](architecture/README.md) | Working agreements: layering, ownership, branching, PR discipline, runtime boundaries |
| [architecture/decisions/](architecture/decisions/README.md) | Architecture decision records, numbered and never renamed |
| [contracts/](contracts/README.md) | Versioned JSON schemas and contract notes; most schemas are written by a Python function and held to it by a test, and the website generates its types from `ui_view_v1` |
| [operations/](operations/README.md) | The operations guide and newer operational references; the runbooks stay at the root of `docs/` |
| [product/](product/README.md) | The member experience and the roadmap |
| [research/](research/README.md) | The research guide, newer protocols and explanations, and their records; older records stay at the root |
| [specs/](specs/README.md) | The specifications guide: new specifications, and an index of the older ones at the root |
| [images/](images/) | Screenshots that merged pull requests refer to |
| [paper/](paper/README.md) | The walk-forward paper (#1152): commands, input and output digests |

Most documents and all older records sit at the root of `docs/`. Their paths are cited by code,
tests, records and merged pull requests, so they stay where they are. No new living document is
added there: `tests/architecture/test_docs_root.py` holds the living documents at the root to the
list of 2026-10-13, which only shrinks.

## Naming key

The file name says what kind of document it is.

| Pattern | Kind | Rule |
| --- | --- | --- |
| `<name>.json` with `<name>.md` beside it | A measurement record and its readable twin | Never edited after it merges, except by regeneration under the same protocol; needs a row in the [measurements index](measurements_index.md) |
| `<name>_prereg.md`, `<name>_protocol.md` | A pre-registration | Frozen when it merges; a later decision is recorded elsewhere and links back |
| `<name>_spec.md` | A specification of a component or a measurement design | Living; a new one goes in [`specs/`](specs/README.md); `candidate_gate_spec.md` and `production_prediction_spec.md` are embedded in generated records as `source_reference` and never move |
| `<name>_runbook.md` | An operator procedure | Living; kept in step with the commands it names |
| `<name>_note.md` | A note that explains a record or a protocol decision | Read together with the record or protocol it explains |
| Anything else | A living document | Updated when the code it describes changes |

A schema file under `contracts/` is named after its contract version, `<contract>_v<N>.schema.json`.

## Where a new document goes

- A new **record** goes where its runner writes it (the root of `docs/` or `research/`), with
  its index row in the same pull request; the row links the record's Markdown twin, because a
  backticked name is not a link.
- A new **research** protocol or explanation goes in `research/`.
- A new **operational** procedure goes in `operations/`; a new **product** document in
  `product/`; a new **architecture** agreement in `architecture/`; a new **specification** in
  `specs/`; each with a row in its folder's guide.
- No new living document goes at the root of `docs/`; a new record still lands there when
  its runner writes it there.
- A new document is linked from its folder's guide, or from another document a reader reaches
  from this guide. `tests/architecture/test_docs_reachable.py` follows the links from this
  guide and fails on a document under `docs/` they do not reach, apart from the unreachable
  documents of 2026-10-13, a list that only shrinks.
- A **decision with alternatives** goes in a new decision record; a product or operations
  decision without one goes in [decisions.md](decisions.md).

## Records stay where they are

Existing records and pre-registrations remain at their established paths. Tests, runners and
other records cite them, and some paths are embedded in generated bytes, so
[the measurement-artifact decision](architecture/decisions/0003-measurement-artifacts.md)
(rule 5) makes moving one a code change: the tests change with it and the bytes are
regenerated. Add a current-status note to a living document rather than rewriting a historical
result.

The preserved pre-alignment development tree and retired topic commits are on the branch
`archive/pre-main-alignment-20260909`; the `docs/archive/README.md` file on that branch explains
recovery. That aggregate archive is not a branch to merge wholesale into develop.
