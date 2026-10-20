# Historical score training contract

`ScoreReplayBasis` holds historical feature inputs and `ScoreReplayObservation` holds later
settled outcomes. Both are frozen records. The basis needs person, club and position
identities; it has no synthetic player role probabilities or forecast substitution intervals
(`src/squadopt/features/football_score_replay.py:50`,
`src/squadopt/features/football_score_replay.py:76`,
`src/squadopt/features/football_score_replay.py:97`).

This contract supports a later reconstruction from an original public revision. Its reference
decision, original revision recording, historical information cutoff, actual retrieval and
actual generation are distinct fields. Passing validation checks their declared ordering;
it does not turn the reconstruction into an originally captured forecast
(`src/squadopt/features/football_score_replay.py:57`,
`src/squadopt/features/football_score_replay.py:200`).

## Prepare features and outcomes separately

1. Preserve the original revision's `players_raw.csv`, `teams.csv`, `fixtures.csv` and
   `gws/merged_gw.csv`, plus the native fit, native baseline, duration history and duration
   forecast receipts. Supply their named SHA256 values, the full revision identifier and the
   implementation hashes. The contract requires these bindings and verifies that the two
   forecast hashes agree with their manifest entries
   (`src/squadopt/features/football_score_replay.py:35`,
   `src/squadopt/features/football_score_replay.py:189`).
2. Produce the native whole-fixture home and away goal means using historical information.
   Declare the native fit information cutoff and the latest settled training outcome. The
   latter must precede that cutoff, which must be no later than the historical feature cutoff
   (`src/squadopt/features/football_score_replay.py:85`,
   `src/squadopt/features/football_score_replay.py:203`).
3. Produce forecast physical duration separately using completed prior matches. Declare a
   nonempty inventory of their season, gameweek, fixture ID, kickoff and completion bound,
   plus the latest history settlement clock,
   and the duration history and forecast hashes. Duplicate fixtures, the target fixture,
   future seasons and the same or later gameweeks of the target season are rejected. The
   kickoff must precede its completion bound, which cannot exceed the latest history settlement.
   The latest history settlement must precede feature use. Kickoff must fall in its declared season
   (`src/squadopt/features/football_score_replay.py:208`,
   `src/squadopt/features/football_score_replay.py:217`).
4. Attach physical periods, ordered goals, full original-roster exposures, independent FPL
   credits, settlement and outcome acquisition receipts. Validation retains the existing
   period-clock reconciliation, scorer identity, own-goal, exposure and final-score checks;
   a declared dismissal remains unsupported
   (`src/squadopt/features/football_score_replay.py:97`,
   `src/squadopt/features/football_score_replay.py:283`,
   `src/squadopt/features/football_score_state_inputs.py:428`).

The likelihood divides each native whole-fixture mean by forecast physical duration. Actual
target duration supplies realized likelihood exposure only. Feeding that target outcome into
the duration forecast's declared history is rejected. Equal numerical values for forecast and
realized duration can occur with valid separate history and are allowed
(`src/squadopt/prediction/football_score_state.py:218`,
`tests/unit/test_football_score_replay.py:146`,
`tests/unit/test_football_score_replay.py:156`,
`tests/unit/test_football_score_replay.py:296`).

## Fit selection and compatibility

Use `ScoreStateModel.fit` with an explicit allowed-season inventory, fit cutoff and target
gameweeks. Released 2025-26 observations additionally require
`allow_released_2025_26=True`; its default is `False`. Every row's source and population
headers are checked before any row's labels. Acquisition and generation must precede fitting;
target and later gameweeks are excluded
(`src/squadopt/prediction/football_score_state.py:596`,
`src/squadopt/prediction/football_score_state.py:639`,
`src/squadopt/features/football_score_replay.py:248`).

Replay fits record `football_score_public_replay_fit_v2`, the released-season choice and
the replay provenance receipts in a `ScoreReplayMetadata` subclass. Ordinary legacy fits
with the default option retain the original metadata schema and canonical serialization.
Both paths use the same likelihood builder. The experiment receipt and fixed-fifteen reader
accept the new serialized metadata
(`src/squadopt/prediction/football_score_state.py:93`,
`src/squadopt/prediction/football_score_state.py:205`,
`src/squadopt/prediction/football_score_state.py:746`,
`tests/unit/test_football_score_replay.py:162`,
`tests/integration/test_football_score_state_experiment.py:50`).

The live `ScoreFixture` validator and `read_score_snapshot` retain their protected-season and
original-capture rules. Replay opt-in is confined to the training path. Prediction still
requires a live `ScoreFixture` with its separately supplied player interval law
(`src/squadopt/features/football_score_state_inputs.py:160`,
`src/squadopt/features/football_score_state_inputs.py:274`,
`src/squadopt/features/football_score_state_inputs.py:578`,
`src/squadopt/prediction/football_score_state.py:816`,
`tests/unit/test_football_score_replay.py:221`).

The v2 duration inventory binds `(season, gameweek, fixture, kickoff, completed_by)`.
A completion bound means the fixture was observed complete by that instant, not that it
is the actual final-whistle time. Producers must authenticate the bound against retained
source evidence. An original revision declaring a fixture finished may provide a conservative
bound only after its identity and recording clock are independently verified. An earlier
GW number cannot substitute for those clocks
(`src/squadopt/features/football_score_replay.py:66`,
`src/squadopt/features/football_score_replay.py:217`).

New fits reject v1 replay provenance and three-field duration inventories. Explicit old
v1 compact fits remain readable under their original tag; v2 compact fits are also supported.
Canonicalization changes replay metadata identities, requiring an audited metadata reissue
that retains the original records. Unchanged admitted likelihood inputs do not require a
numerical refit. Outcome clocks also use canonical UTC in new fit receipts
(`src/squadopt/features/football_score_replay.py:121`,
`src/squadopt/features/football_score_replay.py:310`,
`src/squadopt/features/football_score_replay.py:348`,
`src/squadopt/prediction/football_score_serving.py:97`).

## Meaning of the receipts

The typed validator checks declared clocks, identities, hash syntax and internal bindings.
It does not read the named source files, recalculate their hashes, authenticate a Git revision
or prove that the supplied forecast was computed from the declared history. Those checks
belong in the separate source producer and its retained evidence. The v2 basis digest seals canonical UTC clocks, sorted named source hashes and sorted duration
history. Equivalent clock spelling or inventory ordering therefore retains its identity;
this is not evidence of those external checks
(`src/squadopt/features/football_score_replay.py:1`,
`src/squadopt/features/football_score_replay.py:121`,
`src/squadopt/features/football_score_replay.py:367`).

`model_use_approved` and its evidence reference record the operator's model-use decision.
They do not assert an upstream data license. Preserve the actual source terms and attribution
references alongside the private source evidence; an unavailable grant must remain described
as unavailable. The typed contract has no source-specific license or game-vintage gate
(`src/squadopt/features/football_score_replay.py:57`,
`src/squadopt/features/football_score_replay.py:197`).

These tests use invented records. Passing them establishes the contract and integration
behavior, not actual-source admission, predictive improvement or live activation. Actual
native baselines and a prior-match duration producer require their own source evidence before
a real replay fit can be assessed
(`tests/unit/test_football_score_replay.py:1`,
`tests/unit/test_football_score_replay.py:45`,
`tests/integration/test_football_score_state_experiment.py:50`).
