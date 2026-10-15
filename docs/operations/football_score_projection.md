# Explicit score interval projection

`project_score_intervals` maps a supplied seven-state native player law to one physical
playing interval per atom. This is a deterministic conditional point approximation,
not a learned substitution-time distribution. The output preserves the original
probabilities and credited minutes exactly
(`src/squadopt/features/football_score_projection.py:1`,
`src/squadopt/features/football_score_projection.py:174`).

## Prior duration and source clocks

`ScoreDurationForecast` contains an explicit target and a nonempty inventory of
`ScorePastDuration` records. The forecast uses the arithmetic mean of their two-period
physical durations. Each record declares season, gameweek, fixture, kickoff, observed
completion bound, exact integer period seconds and event/completion source hashes
(`src/squadopt/features/football_score_projection.py:33`,
`src/squadopt/features/football_score_projection.py:45`,
`src/squadopt/features/football_score_projection.py:108`).

The whole target gameweek, future seasons and repeated fixtures are excluded. History
must be observed complete before both the feature cutoff and source acquisition.
Acquisition, forecast generation and interval generation must precede the decision.
The completion bound is a supplied source observation, not an inferred final-whistle
time. Validation checks declared chronology and hash syntax; the producer must verify
the actual source bytes and their meaning separately
(`src/squadopt/features/football_score_projection.py:1`,
`src/squadopt/features/football_score_projection.py:108`,
`src/squadopt/features/football_score_projection.py:174`).

## The approximation

For forecast physical duration H and credited minutes m, the map is `T(m)=H*m/90`.
It spreads forecast added time uniformly across regulation minutes. A starter plays
from zero to T(m); a substitute plays from H-T(m) to H. A full ninety-minute starter
ends at H. Absence retains a zero interval and the `not_playing` exit policy.
These intervals assume one starter exit and a substitute who finishes the match
(`src/squadopt/features/football_score_projection.py:66`,
`src/squadopt/features/football_score_projection.py:174`).

Every period in the duration history must contain at least 45 physical minutes, so
H is at least 90. Credited-minute atoms above 90 refuse. No input probability or minute
is clipped or renormalized. Generated intervals must pass the existing physical
exposure validator; intervals lost to floating-point rounding refuse. This version
refuses positive cameo90 probability, since
the uniform map would put a ninety-minute nonstarter at physical kickoff. A zero-mass
cameo90 atom retains that boundary representation for the existing input shape, with
its zero support recorded explicitly
(`src/squadopt/features/football_score_projection.py:108`,
`src/squadopt/features/football_score_projection.py:174`,
`tests/unit/test_football_score_projection.py:1`).

With zero score-state coefficients, interval exposure divided by H equals m/90.
The score chain therefore recovers native per-atom Poisson survival and its separate
weighted minute eligibility. A nonlinear learned score process still operates on the
declared point intervals; this does not estimate an empirical interval mixture's
survival. The tests compare zero-process survival through the actual score chain
(`tests/unit/test_football_score_projection.py:1`,
`src/squadopt/prediction/football_score_state.py:803`).

## Receipt and caller responsibilities

The immutable receipt binds the declared native artifact hash, exact supplied native
player values, complete duration forecast, target, clocks and named assumptions.
It records that eligibility was not applied. A changed native minute input requires
a new projection and produces a different receipt. The caller still needs to verify
the full native roster and source bytes, assemble the paired `ScoreFixture`, and run
its existing validator before prediction
(`src/squadopt/features/football_score_projection.py:66`,
`src/squadopt/features/football_score_projection.py:174`,
`src/squadopt/features/football_score_state_inputs.py:273`).

This pure producer performs no acquisition or activation. Mathematical consistency
and source chronology do not establish predictive improvement
(`src/squadopt/features/football_score_projection.py:1`).
