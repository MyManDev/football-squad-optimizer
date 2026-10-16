# `squadopt.data`

The canonical data layer, in two rings ([ARCHITECTURE.md](../../../ARCHITECTURE.md)). Its
vocabulary half (R1) states the canonical player-gameweek schema, the errors, the timestamps
and the identities every other layer agrees on, and validates and cleans data against them. Its
storage half (R4) holds the code that meets the outside world's bytes: the immutable capture
store, local loaders, atomic writes, export tables, digests, the build's source revision, the
mapping of a raw layout onto canonical names, and the `sources` subpackage, which turns each
external source's bytes into canonical tables.

This is the package under `src/squadopt/data`. The repository's `data/` folder is a different
thing: the operational state these modules read and write (captures, the season ledger,
handoffs), described in its own [guide](../../../data/README.md).

Its 34 Python files, 19 at the top level and 15 in `sources/`, are placed below, each in
exactly one family.

Review: İbrahim, the data side ([ownership](../../../docs/architecture/ownership.md)). `schema.py`
is a shared boundary that needs both owners
([shared boundaries](../../../docs/architecture/ownership.md#shared-boundaries)), and the
`club_news*` modules are İbrahim's club news lane.

## The boundary

- **It sits at the bottom of the layer order.** Only `contracts` is below it in the layers list
  of `pyproject.toml`, and `schema.py` is the one module that imports it.
- **No outside world but files and `git`.** It imports no web framework, network client, model
  SDK or `sqlite3` ("Frameworks, network and databases stay in api and platform"): the network
  adapters that take captures are in `squadopt.platform`, and the `sources` modules read bytes
  already on disk.
  It is not a source of "The decision core imports no OS or process module", and its storage
  half uses `os` (`atomic.py`, `_long_paths.py`, `source_revision.py`) and `subprocess`
  (`source_revision.py`, which runs `git`).
- **No laboratory, no scripts, no solver.** "Product does not import the laboratory", "The
  package never imports the repository scripts" and "The CP-SAT solver stays in the decision
  core" each hold it as a source.

Of third-party libraries it imports pandas and NumPy.

## Who may import which half

| Importer | Vocabulary half | Storage half |
| --- | --- | --- |
| `contracts` | No: it sits below `data` in the layer order | No |
| `optimization`, `planning`, `scenarios`, `evaluation`, `prediction` | Yes | No: "The decision core imports no storage or source module" |
| `features`, `live`, `application` | Yes | Only today's 122 direct import edges: "Use cases, domain records and features import no storage or source module" |
| `platform`, `integration`, the laboratory, `scripts/` | Yes | Yes |
| `api` | No: "HTTP adapter uses only public boundaries" | No |

No source of either storage contract may import the package root, which re-exports storage
names (`tests/architecture/test_storage_imports.py`).

## Vocabulary (R1)

| Module | What it does |
| --- | --- |
| `schema.py` | The canonical player-gameweek schema: column names, controlled vocabularies, price factors and grouping and sorting keys, which no other data, feature or prediction module may hard-code. |
| `errors.py` | The data layer's exception hierarchy and error formatting, kept apart from the optimizer's errors. |
| `timestamps.py` | One canonical spelling for the instants this project compares, capture times and deadlines; a naive or local-time timestamp is refused. |
| `identity.py` | Reconciles a live capture's player identities against known history by the persistent player code. |
| `claim_identity.py` | Resolves a claim that names a player in text to the persistent code it means. |
| `validation.py` | Integrity validation of the cleaned canonical dataset; it judges and never repairs. |
| `cleaning.py` | Type coercion and value normalization for canonical player-gameweek data, the one place types change. |
| `cohorts.py` | Nested elite cohorts: who stood in the official Overall league's first N ranks at one pre-deadline capture. |
| `fixtures.py` | Validation of the fixture-level table both sources feed, one row per team per fixture. |

## Storage (R4)

| Module | What it does |
| --- | --- |
| `snapshots.py` | The immutable on-disk store for pre-deadline captures of a live season. |
| `atomic.py` | Creates a file exactly once, atomically: it reports whether it wrote the bytes or found the same bytes there, and refuses different ones. |
| `loaders.py` | Local file loaders for raw player-gameweek data; they read and do not transform. |
| `adapters.py` | The explicit mapping from a raw source's layout (column names, position codes, price unit) onto canonical names. |
| `pipeline.py` | One function for the whole raw-to-canonical path, so the stage order has one owner. |
| `checksums.py` | Content digests over raw bytes, so every manifest means the same SHA-256. |
| `tables.py` | Writes an export table in the bytes every machine agrees on, with one line terminator on every platform. |
| `source_revision.py` | Which commit produced this build, resolved once for everyone who stamps it, by running `git`. |
| `_long_paths.py` | Reaches file system paths that Windows' MAX_PATH would otherwise put out of range. |

## Sources (R4)

Each module of `sources/` knows one external source: its layout, its names, its encodings and
the corrections its data needs.

### The FPL API

| Module | What it does |
| --- | --- |
| `sources/fpl_live.py` | The adapter for a captured pre-deadline snapshot of the live Fantasy endpoints; it reads payloads already on disk and never fetches. |
| `sources/fpl_information.py` | Captured official FPL facts, kept apart from coach interpretation and model features: a view of held bootstrap bytes. |
| `sources/fpl_set_pieces.py` | FPL's published set-piece taker priorities, without reading ranks as probabilities. |

### The historical archive

| Module | What it does |
| --- | --- |
| `sources/vaastav.py` | The adapter for the vaastav Fantasy-Premier-League historical archive: its file layout, column names, position codes and the two corrections its data needs. |
| `sources/football_history.py` | Normalizes recorded archive outcomes and settled single-fixture live outcomes for the football model. |

### Club news

| Module | What it does |
| --- | --- |
| `sources/club_news.py` | The seam to a club's own words: the `ClubNewsProvider` protocol, the shapes its two methods exchange, and a provider that serves a committed synthetic fixture. |
| `sources/club_news_capture.py` | The durable layout of one week's club news: the bytes read, and what a model said of them. |
| `sources/club_news_claims.py` | Turns one stored model response into coded claims, offline and byte for byte; it never calls a model. |
| `sources/club_news_coding.py` | What a model is asked for, and how its answer becomes a citation it cannot have written. |
| `sources/club_news_metadata.py` | Reads publication facts from held source bytes, admitting explicit publication fields only. |
| `sources/club_news_readable.py` | The bytes a person reads, taken from the bytes a host served. |
| `sources/club_news_scope.py` | A conservative competition and time scope from a cited sentence, not from model confidence. |
| `sources/club_news_selection.py` | Conservative source selection before paid coding; it authorizes no claim. |

### The official injury list

| Module | What it does |
| --- | --- |
| `sources/premier_league_injuries.py` | Source-exact facts from the official injury widget, which are neither coach claims nor probabilities. |

## Package surface

| Module | What it does |
| --- | --- |
| `__init__.py` | Re-exports names from `adapters`, `cleaning`, `errors`, `fixtures`, `loaders`, `pipeline`, `schema`, `snapshots` and `validation`. |
| `sources/__init__.py` | Re-exports names from `sources/fpl_live.py` and `sources/vaastav.py`. |

## The port declared here

`ClubNewsProvider` in `sources/club_news.py` is one of the 24 typed `Protocol` classes under
`src/squadopt`: where a club's words come from (`fetch`) and what reads them (`code`). Its
adapters are `FixtureClubNewsProvider` in the same module, which serves the committed fixture,
and the model providers in `squadopt.platform`: `AnthropicClubNewsProvider`
(`club_news_model.py`), `OpenAIClubNewsProvider` (`club_news_openai.py`) and
`GeminiClubNewsProvider` (`club_news_gemini.py`).

## Known violations here

ARCHITECTURE.md measures and schedules these; this list says where they are.

- **One package in two rings, at the bottom of the layer order.** `__init__.py` imports the
  storage modules `adapters`, `loaders`, `pipeline` and `snapshots`, so importing any module of
  this package loads those four at run time; `sources/__init__.py` likewise loads `fpl_live`
  and `vaastav` with any `sources` module. The contract "The decision core imports no storage or
  source module" and `tests/architecture/test_storage_imports.py` keep the import statements of
  the clean packages off the storage half; neither stops the run-time load. Splitting the
  package is an open question in
  [ADR 0010](../../../docs/architecture/decisions/0010-clean-architecture-rings-and-repository-layout.md).
- **Three vocabulary modules import the storage half.** `claim_identity.py` imports
  `RosterPlayer` from `sources/club_news.py`, `cleaning.py` imports `PriceUnit` from
  `adapters.py`, and `cohorts.py` imports `LeagueStandingsPage` from `sources/fpl_live.py`. The
  remedy is to move the three types into the vocabulary half with a one-release re-export, with
  the split of the package; the data owner decides.

`source_revision.py` runs `git` by design, as an adapter. That `application/advice_record.py`
reaches it from the use-case ring is a known violation of `squadopt.application`, listed in its
[guide](../application/README.md#known-violations-here).
