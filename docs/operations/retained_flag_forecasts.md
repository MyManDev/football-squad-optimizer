# Retained categorical flags in an optional football forecast

The explicit retained-capture selection produces
`football_joint_role_retained_flags_v1`. Its learned whole-week appearance and
starting/cameo minute law replace the captured eligibility rule in the first
gameweek. Later weeks retain the existing rule, because a next-event label is
only evidence about that named event (`src/squadopt/application/football_live.py:658`,
`src/squadopt/live/football_artifact.py:185`,
`src/squadopt/live/minute_evidence.py:371`).

This is a preparation command. The member discovery path requires a complete
ready bundle before it serves a joint-role variant. Producing a forecast does
not supply that marker (`src/squadopt/platform/advice_switches.py:597`,
`scripts/build_football_forecast.py:213`).

## Original inputs and historical reconstruction

Supply original pre-decision and settled capture IDs, one pair per earlier
gameweek in the target season. Metadata clocks must follow the first deadline
of that season and precede the target capture before any training payload is
read. Reconstruction then excludes repeated, target and future gameweeks
(`scripts/build_football_forecast.py:24`,
`src/squadopt/application/football_live.py:582`).

This clock preflight excludes every GW1 pair: its pre-decision capture must
precede the first deadline, so it cannot satisfy `first_deadline <= captured`
(`scripts/build_football_forecast.py:41`,
`src/squadopt/features/football_flag_captures.py:117`,
`src/squadopt/application/football_live.py:630`).

Each historical native model sees the explicitly selected archives and the
captured season. The retained role model also accepts 2025-26 when it is named;
omitting it retains the three-archive population
(`src/squadopt/application/football_live.py:238`,
`scripts/build_football_forecast.py:148`). Historical `capture_age_hours` and
`news_age_hours` use deadline minus one second in both training and serving.
The operator's decision remains the recorded admission and provenance clock;
changing it alone leaves the fitted law unchanged, while its input receipt
still records the distinct decision. The source capture must precede the fixed
age reference, and the operator's decision must follow the capture and precede
the deadline. The historical clock is an out-of-fold reconstruction with the
actual capture clock retained separately. It does not claim an original forecast
at that time or introduce later flags or news into the earlier capture
(`src/squadopt/application/football_live.py:591`,
`src/squadopt/application/football_live.py:630`,
`src/squadopt/application/football_live.py:708`,
`src/squadopt/features/football_flag_captures.py:119`,
`src/squadopt/features/football_flag_captures.py:134`,
`src/squadopt/features/football_flag_captures.py:173`,
`src/squadopt/features/football_flag_captures.py:188`,
`tests/unit/test_football_flag_captures.py:127`).

A retained fitted flag head may serve a later capture of its same target week;
the serialized cutoff preserves the head's actual fitted cutoff and the reader
requires timezone-aware clocks with `fit_cutoff <= capture < decision < deadline`
(`src/squadopt/application/football_live.py:729`,
`src/squadopt/prediction/football_flag_components.py:371`).

The original FPL person code, full captured club calendar, categorical status,
nullable next-event label and seven native minute states are checked together.
Missing flag history stays missing. Settled training labels require explicit
recorded starts and minutes for a single fixture; weekly totals cannot identify
each role in a double. Pair only weeks in which every club had exactly one
fixture and that fixture settled in the same gameweek. One player-week with a
missing, doubled or unsettled fixture refuses the whole reconstruction, rather
than dropping that player or week. These retained flag labels come from current-season
capture pairs, separately from the native model's historical archive selection.
Target/future flag outcomes are refused before decoding
(`src/squadopt/application/football_live.py:602`,
`src/squadopt/features/football_flag_captures.py:97`,
`src/squadopt/features/football_flag_captures.py:207`,
`src/squadopt/features/football_flag_captures.py:231`,
`src/squadopt/features/football_flag_captures.py:246`,
`src/squadopt/application/football_live.py:638`).

## Prepare an isolated artifact pair

Replace the capture IDs and UTC decision time below with actual retained inputs.
The target decision must follow the capture and precede its deadline. The
training-season arguments name the three baseline archives, the target season
and, optionally, the newly permitted 2025-26 native history
(`scripts/build_football_forecast.py:148`).

```powershell
$env:PYTHONPATH = 'src'
.venv/Scripts/python -m scripts.build_football_forecast `
  --snapshot-root data/snapshots `
  --snapshot-id TARGET_CAPTURE `
  --archive-root data/raw/vaastav-fpl `
  --artifact-root data/artifacts/retained-football `
  --training-season 2022-23 --training-season 2023-24 `
  --training-season 2024-25 --training-season 2025-26 --training-season 2026-27 `
  --role-minutes --retained-role-history --with-components `
  --flag-training-capture BEFORE_CAPTURE SETTLED_CAPTURE `
  --flag-decision-at ACTUAL_UTC_DECISION
```

The producer fits offline, preserves club attacking totals and serializes the
joint weekly law beside its model and native-basis fingerprints. Read-side
validation checks the joint law against the fixture minute marginals, and
minute-only news preserves its weekly appearance hurdle
(`src/squadopt/application/football_live.py:686`,
`src/squadopt/prediction/football_flag_components.py:162`,
`src/squadopt/prediction/football_flag_components.py:332`,
`src/squadopt/live/minute_evidence.py:639`).

The synthetic integration checks exercise 1/3/5-week reads, first-week double
dependence, explicit minute news, single application of flag inputs and the
sealed HTTP/worker/cache path. These are behavior checks; they establish no
accuracy improvement (`tests/integration/test_live_football_flags.py:254`,
`tests/integration/test_live_football_flags.py:290`,
`tests/integration/test_live_football_flags.py:303`,
`tests/integration/test_live_football_flags.py:333`,
`tests/integration/test_live_football_flags.py:348`).

Two original synthetic capture pairs also pass through the real training-row
reconstruction and capture readers with only native model fitting substituted.
The checks pin the reference clock, exact per-week event payload, same-season
pairing, unique historical weeks and settlement before the target capture.
Separate adapter checks reject calendar and fixture-identity mismatches. The
clock-invariance check fits varied capture ages from 2 to 48 hours, so it can
detect decision-time dependence in the learned law
(`tests/integration/test_reconstruct_football_flags.py:44`,
`tests/integration/test_reconstruct_football_flags.py:144`,
`tests/unit/test_football_flag_captures.py:127`,
`tests/unit/test_football_flag_captures.py:152`,
`tests/unit/test_football_flag_captures.py:163`).
