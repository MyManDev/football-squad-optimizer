# `squadopt.features`

The feature engineering of the model lane (R2, [ARCHITECTURE.md](../../../ARCHITECTURE.md)):
leakage-safe features built only from gameweeks before the target, the deadline-safe evidence
tables a decision reads, the record of what happened, and the inputs of the private football
models. Every time-dependent aggregation of the feature builder passes through one
shifted-rolling primitive, so the timing rule has one implementation. Its callers are `prediction`, `live`, `application`, `platform`,
the laboratory and the scripts.

Its 31 Python files sit in one folder. This page places every one of them in exactly one
family.

Review: İbrahim, the data side ([ownership](../../../docs/architecture/ownership.md)).

## The boundary

- **It imports inward only.** The layers list in `pyproject.toml` places it below `prediction`
  and above `data`, so it may import `data` and `contracts`; today it imports `data` only.
- **Storage imports are held to today's.** "Use cases, domain records and features import no
  storage or source module" fails on any new import of the storage half of `squadopt.data`;
  today's are listed below, and `tests/architecture/test_storage_imports.py` refuses an import
  of the `data` package root.
- **No laboratory, no outside world.** It imports no laboratory module ("Product does not import
  the laboratory"), no web framework, network client, model SDK or `sqlite3` ("Frameworks,
  network and databases stay in api and platform"), no repository script ("The package never
  imports the repository scripts") and no `ortools` ("The CP-SAT solver stays in the decision
  core").

Of third-party libraries it imports pandas and NumPy.

## Leakage-safe features

| Module | What it does |
| --- | --- |
| `builder.py` | Attaches leakage-safe rolling features to a canonical player-gameweek dataset: every aggregation is grouped by season and player and shifted by one gameweek before its window. |
| `rolling.py` | The single shifted-rolling primitive: every time-dependent aggregation goes through it, so there is one place to audit the timing rule. |
| `config.py` | Explicit configuration and naming of the rolling features, with the windows declared rather than inlined so they can be experimental factors; and the package's errors (`FeatureError`, `FeatureConfigurationError`). |
| `fixtures.py` | Attaches a gameweek's fixture context to the player-gameweek panel: how many fixtures, at home and away, and their difficulty. |
| `strength.py` | Opponent strength estimated from shifted results we hold, rather than taken from the source's difficulty rating. |
| `cross_season.py` | Carries a player's earlier-season record into a new season, where the rolling features reset. |

## Deadline evidence

Tables a decision reads, each built from what was knowable before the deadline, and the readers
that check them before a row is returned.

| Module | What it does |
| --- | --- |
| `evidence.py` | The deadline-safe player evidence table Phase C reads (`player_evidence_v1`): one row per player per decision week, with a flag wherever a value could be missing. |
| `evidence_artifact.py` | Reads the identity-free Phase B artifact Phase C consumes (`player_evidence_export_v1`). |
| `rotation_evidence.py` | What a club said about who will start, as a table a decision can be made from (`rotation_evidence_v4`): one row per roster player in the decision capture, with absent kept apart from zero. |
| `rotation_evidence_artifact.py` | Reads a `rotation_evidence_v4` pair or a supported legacy pair, checking its digest, manifest, columns and vocabularies, or refuses it. |

## What happened

| Module | What it does |
| --- | --- |
| `component_targets.py` | The Phase C component targets derived from realized outcomes (`phase_c_component_targets_v1`); it refuses to invent the one the canonical panel cannot supply. |
| `settled_outcomes.py` | The prospective record of what actually happened, week by week, from our own captures (`settled_outcome_v1`), and the reader of its exported artifact. |

## Inputs of the football models

The retained flag adapter supplies the optional live producer. The composite recipe also
uses the unit, score, tactical, workload and phase contracts, while the experiment
interfaces retain their training paths (`src/squadopt/application/football_live.py:24`,
`src/squadopt/live/football_composite_basis.py:44`,
`src/squadopt/prediction/football_composite_core.py:21`).
The phase replay and credit readers prepare historical source inputs
(`src/squadopt/features/football_phase_replay.py:123`,
`src/squadopt/features/football_phase_credits.py:106`).

The additional score replay contract is a training input with separate historical feature
and later retrieval clocks. It carries roster identities without a fabricated player minute
law (`src/squadopt/features/football_score_replay.py:50`,
`src/squadopt/features/football_score_replay.py:76`).

| Module | What it does |
| --- | --- |
| `football_flag_inputs.py` | Captured flag facts and supplied pre-decision native minute supports (`football_flag_week_input_v1`); no reader touches a network, a file or an outcome it was not given. |
| `football_flag_captures.py` | Binds original retained FPL flags and explicit settled start/minute labels to causal native supports (`retained_fpl_flag_inputs_v2`), keeping reconstructed decisions distinct from live forecasts (`src/squadopt/features/football_flag_captures.py:97`, `src/squadopt/features/football_flag_captures.py:207`). |
| `football_load_inputs.py` | Immutable all-competition workload and native-law source contracts (`football_load_week_input_v1`). |
| `football_phase_inputs.py` | Causal inputs for phase-specific credited goal and assist allocation (`football_phase_inputs_v1`). |
| `football_phase_replay.py` | Reads exact public-revision duty CSV bytes while retaining separate original-recording and actual-retrieval clocks (`football_phase_replay.py:123`). |
| `football_phase_credits.py` | Binds final FPL assists only when independent totals force a unique event assignment; refuses ambiguous assignments (`football_phase_credits.py:106`). |
| `football_phase_coupling.py` | Explicit circular joint participation construction preserving supplied seven-state native marginals; dependence is imposed by persistent identity order (`src/squadopt/features/football_phase_coupling.py:103`). |
| `football_score_state_inputs.py` | Strict score-process inputs (`football_score_fixture_input_v1`); a receipt assertion does not admit real data. |
| `football_score_projection.py` | Explicit uniform forecast-clock point intervals preserve supplied native minute atoms; past duration receipts and approximation assumptions remain separate from a learned substitution law (`football_score_projection.py:174`). |
| `football_tactical_inputs.py` | Named tactical facts and supplied paired pre-decision states (`football_tactical_inputs_v1`). |
| `football_unit_inputs.py` | Immutable inputs of the separately invoked club-unit experiment (`football_unit_inputs_v1`). |
| `football_unit_catalog.py` | The strict private JSON input boundary of the club-unit experiment; it touches no network or file. |
| `football_fm_attributes.py` | Reads a full private FM export and prepares its exact active player/club scope for a catalog (`football_fm_csv_attributes_v1`, `football_fm_scoped_attributes_v1`), retaining unknown traits and refusing inferred identity or absent mapped UIDs (`src/squadopt/features/football_fm_attributes.py:296`). |
| `football_unit_point.py` | Declared deterministic XI point from complete native starter probabilities, with exact structural support and a retained basis receipt (`src/squadopt/features/football_unit_point.py:48`). |
| `football_score_replay.py` | Frozen historical score training records, explicit 2025-26 opt-in and declared native/duration source bindings (`src/squadopt/features/football_score_replay.py:121`); [operator contract](../../../docs/operations/football_score_replay.md). |

Observed workload and tactical context have separate typed input boundaries
(`src/squadopt/features/football_observed_load.py:130`,
`src/squadopt/features/football_observed_tactical_inputs.py:134`):

| Module | What it does |
| --- | --- |
| `football_observed_load.py` | Observed non-PL reported-record inputs and retrospective provenance, preserving missing values and complete native PL support (`src/squadopt/features/football_observed_load.py:130`). |
| `football_observed_tactical_inputs.py` | Separate full-roster native marginal context with four observed event channels, nullable FM traits and prior provider roles; explicit historical replay retains actual acquisition clocks (`src/squadopt/features/football_observed_tactical_inputs.py:134`, `src/squadopt/features/football_observed_tactical_inputs.py:386`). |
| `football_observed_tactical_readers.py` | Pure byte readers for typed observed-tactical envelopes, complete selected event rows, exact FM rows and provider roles; supplied SHA256 checks establish byte integrity (`src/squadopt/features/football_observed_tactical_readers.py:45`, `src/squadopt/features/football_observed_tactical_readers.py:155`, `src/squadopt/features/football_observed_tactical_readers.py:276`, `src/squadopt/features/football_observed_tactical_readers.py:406`). |

## Package surface

| Module | What it does |
| --- | --- |
| `__init__.py` | Re-exports names from `builder`, `config`, `cross_season`, `fixtures`, `rolling` and `strength`. |

## Known violations here

ARCHITECTURE.md measures and schedules these; this list says where they are.

- **Storage imports.** 4 modules import the storage half of `squadopt.data` directly: 16 edges
  from `evidence`, `football_phase_inputs`, `rotation_evidence` and
  `rotation_evidence_artifact` to `data.snapshots`, `data._long_paths`,
  `data.sources.fpl_live`, `data.sources.fpl_set_pieces` and five `data.sources.club_news*`
  modules. Each edge is an `ignore_imports` entry of "Use cases, domain records and features
  import no storage or source module" and may only go. The remedy is storage ports declared in
  `squadopt.application`, with file adapters in `platform` (Phase 3).
- **File access.** `evidence_artifact.py`, `rotation_evidence_artifact.py` and
  `settled_outcomes.py` read their artifacts' manifests and tables themselves. The remedy is the
  same storage ports (Phase 3). Until then `tests/architecture/test_use_case_file_io.py`
  allowlists these 3, and fails on any other module here that reads or writes a file.
