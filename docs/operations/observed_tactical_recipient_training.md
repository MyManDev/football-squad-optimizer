# Observed tactical recipient training

`football_observed_tactical_recipients_v1` is a distinct training contract for the
conditional goal and assist recipient likelihoods. Its metadata contains two transforms,
two coefficient vectors, support counts, optimizer receipts and complete training-source
receipts. It has no team transform, physical-rate coefficient vector or count-head
placeholder (`src/squadopt/prediction/football_observed_tactical_recipients.py:36`,
`src/squadopt/prediction/football_observed_tactical_recipients.py:41`).

The recipient model and full observed-tactical model share the same header validation,
recipient feature construction, training-only value/mask transforms and conditional
likelihood arithmetic. All observation headers pass before outcome validation. Native
shares remain the recipient offsets, with one-half native-share training weight per
club. The recipient model calls only these two optimizers. The full model continues
to fit its original paired-rate head and wrap its original metadata
(`src/squadopt/prediction/football_observed_tactical.py:498`,
`src/squadopt/prediction/football_observed_tactical.py:533`,
`src/squadopt/prediction/football_observed_tactical.py:647`,
`src/squadopt/prediction/football_observed_tactical_recipients.py:134`).

The defaults remain alpha 0.1 and a maximum of 500 iterations. A failed optimizer result
refuses the fit and retains bounded diagnostic declarations including the head, reported
status, success, iteration/evaluation counts, finite reported objective and coefficient
shape/type. Invalid declarations remain unknown instead of being coerced into successful
results. A failed refit preserves any earlier fitted recipient model
(`src/squadopt/prediction/football_observed_tactical_recipients.py:103`,
`src/squadopt/prediction/football_observed_tactical_recipients.py:134`,
`src/squadopt/prediction/football_observed_tactical.py:295`,
`src/squadopt/prediction/football_observed_tactical.py:327`).

Prediction uses the shared recipient-only allocator, preserving native zero support,
head-support and mass checks, prospective clocks and the fitted target window. Compact
serving accepts the distinct recipient model version and fit scope; its receipt retains
the corresponding original metadata digest. A recipient-only fit does not establish
successful fitting of a paired-rate model
(`src/squadopt/prediction/football_observed_tactical_recipients.py:187`,
`src/squadopt/prediction/football_observed_tactical.py:426`,
`src/squadopt/prediction/football_observed_tactical_serving.py:212`,
`src/squadopt/prediction/football_observed_tactical_serving.py:329`).

The tests forbid count-head access, compare exact recipient transforms, coefficients,
optimizer receipts and predictions against a successfully fitted full model, and check
chronology, release permission, unsupported heads and failure diagnostics. These use
invented fixtures and make no accuracy or runtime-activation claim
(`tests/unit/test_football_observed_tactical_recipients.py:1`).
