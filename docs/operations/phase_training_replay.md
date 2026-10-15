# Phase training from original revisions

The phase input path accepts a separately identified reconstruction from immutable public
revisions. The original revision time, actual retrieval time, feature cutoff and current
generation time remain separate in `PhaseReplay`; the fit carries that receipt into its
training metadata (`src/squadopt/features/football_phase_inputs.py:111`,
`src/squadopt/prediction/football_phase_duties.py:432`).

## Source preparation

Supply exact `players_raw.csv` and `teams.csv` bytes with their SHA256 receipts to
`read_replayed_phase_duties`. It checks the source hashes, original Git revision, player and
club identities, and duty ranks. Blank and literal `None` ranks remain unknown. The returned
duty receipt names `git:<revision>` and retains the actual retrieval clock
(`src/squadopt/features/football_phase_replay.py:122`).

Bind the original roster, clubs, fixture calendar and history hashes in `PhaseReplay`.
Include the hashes of every additional historical input and the exact native feature code
used by the producer. Retain the reconstructed baseline bytes and their actual generation
receipt. The reader requires the original revision before the feature cutoff, settled history
before that cutoff, and actual acquisition and generation before training. An original
held forecast is not established by this reconstruction
(`src/squadopt/features/football_phase_inputs.py:374`).

Supply every physical goal of the selected club-fixture, independently verified scoring
identities and supported phase definitions to `bind_unique_phase_credits`. It binds assists
only if the independent final FPL totals permit exactly one assignment. Provider assist
actors are not inputs; a same-player goal and assist is refused, and ambiguous assignments
remain unavailable (`src/squadopt/features/football_phase_credits.py:24`,
`src/squadopt/features/football_phase_credits.py:106`).

## Explicit fitting population

Pass `replay` and `allow_released_2025_26=True` to `read_phase_observation`, and the same
released-season option to `PhaseDutyModel.fit` when that season is selected. The default
continues to exclude it. The whole target gameweek stays excluded, and source clocks,
complete captured-club rosters, observed exposure and independent final credits still pass
their validators (`src/squadopt/features/football_phase_inputs.py:306`,
`src/squadopt/features/football_phase_inputs.py:441`,
`src/squadopt/features/football_phase_inputs.py:732`,
`src/squadopt/prediction/football_phase_duties.py:326`).

Record the selected and refused fixture population, the reasons for refusal, source evidence
for each phase, and event support for every fitted head with the private fit. Do not interpret
an unsupported phase as a measured zero: the model estimates its phase mixture directly
from the admitted event counts (`src/squadopt/prediction/football_phase_duties.py:385`).

Replayed or released-season fits carry `football_phase_duty_replay_fit_v1` metadata, the
release selection and per-observation replay receipts. These are training provenance, not
an accuracy reading or a runtime activation receipt
(`src/squadopt/prediction/football_phase_duties.py:432`). Keep original source tables,
prepared observations and fitted artifacts outside tracked files.
