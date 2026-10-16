# Phase training from original revisions

The phase input path accepts a separately identified reconstruction from immutable public
revisions. The original revision time, actual retrieval time, feature cutoff and current
generation time remain separate in `PhaseReplay`; the fit carries that receipt into its
training metadata (`src/squadopt/features/football_phase_inputs.py:111`,
`src/squadopt/prediction/football_phase_duties.py:434`).

## Training decision recorded on 16 October 2026

The task owner authorized 2025-26 outcomes, including phase labels, for experimental
football training and accepted that those outcomes lose independent-test status.
The same training task admits immutable public-revision reconstruction as a historical
basis, with its actual retrieval clock retained. The authorization is disclosed in
[the integration pull request](https://github.com/MyManDev/football-squad-optimizer/pull/1120).
It covers this experimental training task; the default `current` selection and a later
ANN remain outside this decision. A native-history release alone is not the phase-label
decision. This permission does not establish upstream source authenticity or licensing:
the caller must still supply admitted model-use evidence for every source
(`src/squadopt/features/football_phase_replay.py:146`,
`src/squadopt/features/football_phase_inputs.py:213`).

## Source preparation

Supply exact `players_raw.csv` and `teams.csv` bytes with their SHA256 receipts to
`read_replayed_phase_duties`. It compares the supplied roster and club bytes with their hashes,
checks the Git revision's format, and validates player and club identities and duty ranks.
Blank and literal `None` ranks remain unknown. The returned
duty receipt names `git:<revision>` and retains the actual retrieval clock. Its
`valid_until` must cover the historical decision and be strictly before retrieval.
Consequently its retrieval time cannot fall inside its validity interval, and the
returned receipt cannot pass as an original capture or a projection duty capture.
The observation validator repeats this validity check for direct or restored captures;
original and projection validation also reject the known `git:` replay identity
(`src/squadopt/features/football_phase_replay.py:69`,
`src/squadopt/features/football_phase_replay.py:118`,
`src/squadopt/features/football_phase_inputs.py:248`,
`src/squadopt/features/football_phase_inputs.py:445`,
`src/squadopt/features/football_phase_inputs.py:525`).

Bind the original roster, clubs, fixture calendar and history hashes in `PhaseReplay`.
Include the hashes of every additional historical input and the exact native feature code
used by the producer. These additional input hashes are retained as receipts; only the roster
and club bytes supplied to the duty reader are checked against their replay source hashes
(`src/squadopt/features/football_phase_replay.py:69`,
`src/squadopt/features/football_phase_replay.py:157`,
`src/squadopt/features/football_phase_inputs.py:389`).

Retain the reconstructed baseline bytes and their actual generation receipt. The observation
reader checks the declared revision time before the feature cutoff, the declared latest
history kickoff before that cutoff, and declared acquisition and generation before training.
It checks the declared clocks' order; it does not verify these clocks against the Git commit
or the baseline bytes. An original held forecast is not established by this reconstruction
(`src/squadopt/features/football_phase_inputs.py:434`).

Supply every physical goal of the selected club-fixture, independently verified scoring
identities and supported phase definitions to `bind_unique_phase_credits`. It binds assists
only if the independent final FPL totals permit exactly one assignment. Provider assist
actors are not inputs; a same-player goal and assist is refused, and ambiguous assignments
remain unavailable (`src/squadopt/features/football_phase_credits.py:24`,
`src/squadopt/features/football_phase_credits.py:106`).

## Explicit fitting population

Pass `allow_released_2025_26=True` to `read_phase_observation` and `PhaseDutyModel.fit`
when that season is selected. This option admits both original-capture and replayed
observations; it does not turn an original capture into a replay. For a reconstruction,
also pass the option to `read_replayed_phase_duties` and supply `replay` to both readers.
All three default to excluding that season and require a Boolean release option
(`src/squadopt/features/football_phase_replay.py:133`,
`src/squadopt/features/football_phase_inputs.py:308`,
`src/squadopt/features/football_phase_inputs.py:771`,
`src/squadopt/prediction/football_phase_duties.py:335`).
The whole target gameweek stays excluded, and declared source clocks,
complete captured-club rosters, observed exposure and independent final credits still pass
their validators (`src/squadopt/features/football_phase_inputs.py:308`,
`src/squadopt/features/football_phase_inputs.py:463`,
`src/squadopt/features/football_phase_inputs.py:757`,
`src/squadopt/prediction/football_phase_duties.py:327`).

A fit requires exactly one declared FPL rules version. Original and replayed rows may
share a fit only when their rules version agrees; mixed versions refuse before event
labels are inspected (`src/squadopt/prediction/football_phase_duties.py:372`).

Record the selected and refused fixture population, the reasons for refusal, source evidence
for each phase, and event support for every fitted head with the private fit. Do not interpret
an unsupported phase as a measured zero: the model estimates its phase mixture directly
from the admitted event counts (`src/squadopt/prediction/football_phase_duties.py:388`).

New fits emit `football_phase_duty_replay_fit_v2` when an admitted row is replayed or belongs
to 2025-26; otherwise they emit `football_phase_duty_fit_v2`. `released_2025_26` records
actual row use, while `allowed_seasons` retains the supplied allowlist. Selecting the option
without using a released row or replay leaves an ordinary fit. The v2 tags distinguish the
metadata shape containing replay receipts and the release field from the earlier v1
contract (`src/squadopt/prediction/football_phase_duties.py:84`,
`src/squadopt/prediction/football_phase_duties.py:106`,
`src/squadopt/prediction/football_phase_duties.py:434`).

Replay receipts sort named source hashes and normalize UTC clocks before observation hashing
and metadata retention. Original observations keep their earlier digest encoding
(`src/squadopt/features/football_phase_inputs.py:376`,
`src/squadopt/features/football_phase_inputs.py:576`,
`src/squadopt/prediction/football_phase_duties.py:466`). Compact serving still accepts the
existing v1 fit tags with their original release-option semantics and accepts the v2 tags
with actual-row semantics; it retains exact shape and hash validation. Old artifacts are
not relabelled or silently rehashed (`src/squadopt/prediction/football_phase_serving.py:129`,
`src/squadopt/prediction/football_phase_serving.py:174`,
`src/squadopt/prediction/football_phase_serving.py:354`). Keep original source tables,
prepared observations and fitted artifacts outside tracked files.

## Population limitation

Unique-assignment admission conditions the selected population on final outcomes. With
multiple goals, ambiguity depends on how credits can be exchanged between events, so an
admitted sample can favor concentrated assist patterns. The binder deliberately refuses
multiple valid assignments; this is a selection limitation, not an accuracy result
(`src/squadopt/features/football_phase_credits.py:106`,
`src/squadopt/features/football_phase_credits.py:166`). A later accuracy study must address
that selection before interpreting delivery-rank coefficients. This change adds no accuracy
comparison or multi-goal coefficient experiment.
