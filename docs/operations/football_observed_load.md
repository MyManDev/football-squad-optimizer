# Observed non-PL workload model

`ObservedLoadModel` fits a reweighting of a supplied whole-week native minute
law from named observed non-PL records. Its input and feature contracts are
separate from the complete all-competition workload model
(`src/squadopt/features/football_observed_load.py:32`,
`src/squadopt/prediction/football_observed_load.py:317`).

## Source and clock admission

The named scope is Champions League, Conference League, EFL Cup and Europa League.
Case, spaces and underscores normalize to the explicit hyphenated names for scope
validation; unknown names and duplicate aliases refuse. Each record must bind its
persistent player, exact declared competition, source line and hashes, and original
finished revision. Missing records do not establish nonappearance, and unknown
minutes or starts remain distinct from zero
(`src/squadopt/features/football_observed_load.py:35`,
`src/squadopt/features/football_observed_load.py:212`,
`src/squadopt/features/football_observed_load.py:367`).

`completed_by` is the bound by which the source observed the fixture finished.
The reader checks its declared chronology and source manifest; external source
bytes and original Git revision authenticity remain the producer's responsibility
(`src/squadopt/features/football_observed_load.py:212`).

A `public_revision_replay` records actual later retrieval and generation, while
its source revision must already have been recorded by the historical feature
cutoff. Later corrected minutes cannot be relabelled as earlier observations.
A prospective input orders recording, retrieval and generation, with generation
by feature use and feature use by the operator decision. Records must have
completed before feature use and their original source recording. Record admission
uses the fixed feature cutoff's 28-day inventory
(`src/squadopt/features/football_observed_load.py:252`,
`src/squadopt/features/football_observed_load.py:342`,
`tests/unit/test_football_observed_load.py:843`,
`tests/unit/test_football_observed_load.py:854`).

The separate native law requires the complete Premier League fixture calendar,
canonical joint states, exact marginals and source identities. Captured native
inputs retain their original snapshot identity and clocks; they are prospective
only. They do not fabricate a Git revision. Declared clocks and hashes are
validated without opening external source files
(`src/squadopt/features/football_observed_load.py:108`,
`src/squadopt/features/football_observed_load.py:212`,
`src/squadopt/features/football_observed_load.py:477`).

## Fixed feature reference and fitting

The 24 features contain eight statistics for each 7, 14 and 28-day window:
record count, known and unknown minute counts, known-minute sum, known and unknown
start counts, confirmed-start sum, and hours since the latest observed positive
kickoff. Both training and serving use deadline minus one second for the windows
and age. The operator decision remains an admission and provenance clock.
An unchanged observation set and deadline therefore give identical features and
served probabilities at different valid decision times
(`src/squadopt/features/football_observed_load.py:41`,
`src/squadopt/features/football_observed_load.py:367`,
`src/squadopt/prediction/football_observed_load.py:150`,
`src/squadopt/prediction/football_observed_load.py:163`,
`tests/unit/test_football_observed_load.py:878`).

The feature version is `observed_non_pl_deadline_relative_records_v2`.
Old decision-relative fitted and compact artifacts fail version validation and
must be refitted from independently admitted original inputs. The reader does
not relabel old coefficients as the new feature version
(`src/squadopt/features/football_observed_load.py:34`,
`src/squadopt/prediction/football_observed_load.py:253`,
`src/squadopt/prediction/football_observed_load.py:545`,
`tests/unit/test_football_observed_load.py:780`).

Training checks every header before labels, refuses target and later weeks, and
requires explicit Boolean permission for released 2025-26 data. The transform
learns from training values only and refuses newly observed features without
training support. Structural zeros remain zero; zero coefficients recover the
normalized original joint law. The standalone predictor applies no eligibility
multiplier and requires a prospective input in its fitted target and scope
(`src/squadopt/features/football_observed_load.py:402`,
`src/squadopt/prediction/football_observed_load.py:163`,
`src/squadopt/prediction/football_observed_load.py:241`,
`src/squadopt/prediction/football_observed_load.py:317`,
`src/squadopt/prediction/football_observed_load.py:427`).

## Compact serving and composition

The immutable compact model contains inference parameters and the fitted metadata
hash, with its own byte identity. Reading it validates canonical bytes, versions,
finite coefficients and transform support without fitting. Publication must also
verify correspondence to the retained full training metadata
(`src/squadopt/prediction/football_observed_load.py:473`,
`src/squadopt/prediction/football_observed_load.py:545`).

The composite caller applies LOAD only to the first forecast week. Later weeks
receive the declared shared captured-eligibility mixture without LOAD, pending a
model trained for their forecast horizons. Actual source admission and regenerated
artifacts remain required before publishing a forecast
(`src/squadopt/prediction/football_composite_weeks.py:366`).
