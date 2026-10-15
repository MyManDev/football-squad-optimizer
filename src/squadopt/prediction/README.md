# `squadopt.prediction`

The model lane of the domain ring (R2, [ARCHITECTURE.md](../../../ARCHITECTURE.md)): player
projections and the optimizer-ready projection table. It holds the operational control that
decides a live squad, the adjustments applied to a projection, the candidates the laboratory
measures against the control, and the models of the experimental football lane. Its callers
are `live`, `scenarios` and `evaluation` in the domain ring, `application`, `platform`, the
laboratory and the scripts.

Its 45 Python files sit in one folder. This page places every one of them in exactly one
family.

Review: İbrahim, the data side ([ownership](../../../docs/architecture/ownership.md)). Within 24
hours either side of a deadline only a blocker fix merges here
([live-path freeze window](../../../docs/architecture/ownership.md#live-path-freeze-window)).

## The boundary

- **It imports inward only.** The layers list in `pyproject.toml` places it below
  `optimization` and above `features`, so it may import `features`, `data` and `contracts`,
  and today it imports each of them. Of `data` it imports only vocabulary modules (`errors`,
  `schema` and `timestamps`).
- **It imports no storage or source module of `data`.** No contract makes it a source yet:
  "The decision core imports no storage or source module" adds it when its zone owner agrees.
- **It touches no file.** `tests/architecture/test_core_file_io.py` holds it to no `open`,
  no file method of `Path`, no pandas reader or writer it lists and no file function of `os`,
  `glob`, NumPy or joblib, with no allowlist entry.
- **No laboratory, no outside world.** It imports no laboratory module ("Product does not import
  the laboratory"), no web framework, network client, model SDK or `sqlite3` ("Frameworks,
  network and databases stay in api and platform"), no repository script ("The package never
  imports the repository scripts") and no `ortools` ("The CP-SAT solver stays in the decision
  core").

Of third-party libraries it imports pandas, NumPy, SciPy and scikit-learn.

## The projection table and its hand-off

| Module | What it does |
| --- | --- |
| `projection.py` | Builds the optimizer-ready projection table: raw column names, adapters, cleaning rules and feature windows stop here, and the optimizer sees only the six agreed columns. |
| `baseline.py` | The deterministic baseline expected-points projection: a scoring rate scaled by expected playing time, simple enough to verify by hand. |
| `integration.py` | The model-neutral hand-off from predicted points to the optimizer contract (`prediction_to_optimization_v1`): `PredictionProvenance`, `PredictionSnapshot` and `prepare_optimizer_projection`. |
| `components.py` | Typed component predictions before the point-estimate hand-off (`component_prediction_v1`). |
| `config.py` | Explicit configuration of the baseline projection, its coefficients and fallbacks, and the package's errors (`PredictionError`, `PredictionConfigurationError`). |
| `factors.py` | Maps experiment factors to prediction configuration (`FormWindowMapping`, `form_window_v1`). |

## The operational control

The projection that decides a live squad. `live/recommendation.py` names the opening version,
`opening-carry-over-v1`, and, in `IN_SEASON_CONTROL_MODEL_VERSIONS`, the four versions promoted
to decide a mid-season squad through a handoff: the Phase C control components, the in-season
carry-over, and the Top-100 variant of each.

| Module | What it does |
| --- | --- |
| `opening.py` | Projections for a season that has not started, from a roster and earlier seasons. |
| `in_season.py` | The control extended into a season that has started (`in-season-carry-over-v1`), blending the completed season with the current one. |
| `component_dataset.py` | The leakage-safe modelling frame the Phase C control components are fitted on: which columns may be features and which rows may be training data (`phase_c_component_dataset_v1`). |
| `component_models.py` | The Phase C control components (`phase_c_control_components_v1`): appearance, conditional minutes and conditional points, declared rather than searched. |
| `elite_evidence.py` | The conservative Top-100 evidence adjustment of the operational point handoff (`phase_c_operational_elite_policy_v1`), and the two Top-100 model versions. |

## Adjustments to a projection

| Module | What it does |
| --- | --- |
| `availability.py` | Applies captured availability to a projection as a rule (`captured_availability_rule_v1`), not as a learned feature. |
| `participation_updates.py` | Applies explicit participation evidence to a fresh, identified projection basis: a captured percentage is an eligibility multiplier, and no statement or model confidence becomes a probability. |
| `defcon_component.py` | Fixed DEFCON arithmetic for the proposed #1000 component (`defcon_augmentation_2026_v1`); it fits only the declared 2026-27 event-rate counts, reads no file and promotes no version. |

## Candidates measured against the control

Models the laboratory measures. Outside this package, only `backtest` and measurement runners
under `scripts/` import these modules by their module path; the
[measurements index](../../../docs/measurements_index.md) records what each measurement found.

| Module | What it does |
| --- | --- |
| `production.py` | The two-stage production projection: a scoring rate times expected minutes. It did not clear its development gate (`production_gate_judgement` in the index). |
| `minutes.py` | Expected minutes, the availability half of the two-stage projection. |
| `participation.py` | Whether a player starts given that he plays (`participation_conditional_start_v1`), the conditional half of the participation split. |
| `learned.py` | A deterministic Ridge reference model for one-gameweek points (`ridge-reference-v1`). |
| `learned_rate.py` | The learned scoring rate of issue #43 (`learned-rate-v2`), fitted only on history the decision point can see. |

## The football lane

The models of the experimental football model a member can choose in place of the current
model; the [package map](../README.md#two-cross-cutting-names) describes the lane as a whole.

These eleven are imported by `live`, `application` or `platform`, directly or through one
another:

| Module | What it does |
| --- | --- |
| `football.py` | The opt-in fixture football candidate (`football_team_share_v1`, with its role-transition and joint-role variants); fitting it never changes the promoted control. |
| `football_features.py` | History-only fixture features for the football candidate; target rows supply identity, position and venue only. |
| `football_minutes_role.py` | Joint starting role and fixture minutes (`joint_start_cameo_minutes_v1`), fitted only on known past labels. |
| `football_components.py` | The v1 model's per-fixture components for one capture (`football_fixture_components_v1`), bound to the served forecast of the same producer call. |
| `football_flag_components.py` | Converts a learned whole-week flag law into fixture minutes and nonlinear scoring, conserving each complete club's attacking mass (`src/squadopt/prediction/football_flag_components.py:84`, `src/squadopt/prediction/football_flag_components.py:162`). |
| `football_flag_minutes.py` | A categorical-flag weekly hurdle and conditional fixture-minute model (`football_flag_minutes_v1`), fitted offline by the optional retained-capture producer; source labels remain categories (`src/squadopt/application/football_live.py:686`). |
| `football_contextual.py` | The opt-in contextual extension of the frozen fixture model (`football_contextual_v3`): captured availability enters once, as an eligibility multiplier. |
| `football_strength.py` | A sequential, opponent-adjusted Gamma filter of team scoring strength, used by the contextual extension. |
| `football_match_context.py` | A separate Premier League workload and venue candidate (`football_match_context_v1`). |
| `football_match_context_features.py` | Causal Premier League workload and venue context from recorded player-fixture history, for `football_match_context.py`. |
| `football_team_form.py` | Causal club form for an explicitly selected fixture-football experiment (`football_team_form_v1`). |

These five are private models: outside this package, each is imported only by its
`football_*_experiment` module in [`squadopt.experiments`](../experiments/README.md).

| Module | What it does |
| --- | --- |
| `football_load_minutes.py` | A whole-week workload tilt over an admitted native minute law (`football_all_competition_load_v1`); it never applies player eligibility. |
| `football_phase_duties.py` | Learned goal and assist marginals with conserved full-club attacking mass (`football_phase_duties_v1`); captured ranks are explanatory observations. |
| `football_phase_serving.py` | Compact phase parameter export and byte-checked restoration with a distinct serving receipt; shares allocation arithmetic with the fitted model (`src/squadopt/prediction/football_phase_serving.py:255`, `src/squadopt/prediction/football_phase_serving.py:287`, `src/squadopt/prediction/football_phase_serving.py:337`). |
| `football_score_state.py` | A paired score process with fitted lead and trail intensities in three thirds of the match clock (`football_score_state_v1`). |
| `football_score_serving.py` | Strict compact score parameters with a separate artifact digest and inference receipt (`football_score_serving_v1`). |
| `football_tactical_matchup.py` | Learned paired intensities and conditional tactical recipient marginals from supplied pre-decision states (`football_tactical_matchup_v1`). |
| `football_unit_strength.py` | A baseline-relative projected club-unit model with private inputs (`football_projected_unit_strength_v1`). |

The compact inference boundary has its own result receipt
(`src/squadopt/prediction/football_unit_serving.py:109`).

| Module | What it does |
| --- | --- |
| `football_unit_serving.py` | Exports and strictly reads immutable pooled v4 parameters, then predicts paired rates from current typed unit inputs (`src/squadopt/prediction/football_unit_serving.py:290`, `src/squadopt/prediction/football_unit_serving.py:394`, `src/squadopt/prediction/football_unit_serving.py:470`). |
| `football_composite_core.py` | Composes current compact family models over final seven-atom minute marginals, with distinct source and derived-stage receipts and exact full bypass (`src/squadopt/prediction/football_composite_core.py:160`, `src/squadopt/prediction/football_composite_core.py:192`, `src/squadopt/prediction/football_composite_core.py:597`). |
The following standalone model has its own source contract:

| Module | What it does |
| --- | --- |
| `football_observed_load.py` | Observed non-PL reported-record tilt of the whole native weekly law, with distinct missing-value features and no product caller (`src/squadopt/prediction/football_observed_load.py:295`). |
A separate observed-scope model has no runtime caller in this change. Its allocation carries
paired rates and recipient marginals, with its explicit context policy in metadata
(`src/squadopt/prediction/football_observed_tactical.py:180`,
`src/squadopt/prediction/football_observed_tactical.py:212`).

| Module | What it does |
| --- | --- |
| `football_joint_week_law.py` | Pure whole-week flag/LOAD transport and explicit evidence interventions with immutable joint support and lineage (`src/squadopt/prediction/football_joint_week_law.py:37`). |
| `football_observed_tactical.py` | Fits paired Poisson rates and conditional goal/assist recipients at full-roster native marginal context, with training-only observed-value transforms and missingness masks; exposes recipient-only inference without the count head (`src/squadopt/prediction/football_observed_tactical.py:91`, `src/squadopt/prediction/football_observed_tactical.py:647`, `src/squadopt/prediction/football_observed_tactical.py:750`). |
| `football_observed_tactical_recipients.py` | Fits only conditional goal/assist recipient heads under a distinct metadata contract, retaining native offsets, training receipts and diagnostics (`src/squadopt/prediction/football_observed_tactical_recipients.py:41`, `src/squadopt/prediction/football_observed_tactical_recipients.py:134`). |
| `football_observed_tactical_serving.py` | Exports and restores compact recipient parameters with explicit byte integrity and separate original-model provenance; reuses the pure recipient allocator (`src/squadopt/prediction/football_observed_tactical_serving.py:64`, `src/squadopt/prediction/football_observed_tactical_serving.py:329`, `src/squadopt/prediction/football_observed_tactical_serving.py:387`). |

## Package surface

| Module | What it does |
| --- | --- |
| `__init__.py` | Re-exports names from `baseline`, `components`, `config`, `elite_evidence`, `factors`, `integration`, `learned`, `minutes`, `opening`, `production` and `projection`. |

## Known violations here

None of its own in ARCHITECTURE.md's list. One applies through `data`: every `data` module this
package imports runs `src/squadopt/data/__init__.py` first, which loads the storage modules `adapters`,
`loaders`, `pipeline` and `snapshots`, so importing `squadopt.prediction` loads them at run
time although no import statement here names them (the `data` entry, an open question in
ADR 0010).
