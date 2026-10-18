# Joint participation for phase allocation

`couple_phase_minutes` constructs bounded phase states from a complete supplied
club roster and seven native atoms per player: absence, three start minute bins
and three cameo minute bins. It preserves the distinct durations of the start
and cameo atoms (`src/squadopt/features/football_phase_coupling.py:28`,
`src/squadopt/features/football_phase_coupling.py:103`,
`tests/unit/test_football_phase_coupling.py:59`).

The policy sorts persistent player identities and concatenates their six
positive probability intervals around a unit circle. Each player's remaining
arc is absence. Splitting at all endpoints gives at most `6*N+1` states; the
population limit is derived as `(MAX_PHASE_STATES - 1) // 6`, currently 170 for the
shared 1,024-state cap (`src/squadopt/features/football_phase_coupling.py:24`,
`src/squadopt/features/football_phase_inputs.py:34`,
`tests/unit/test_football_phase_coupling.py:193`).
Endpoint comparisons use exact fractions of the supplied binary floats, so
small positive intervals are not silently discarded. Positive atoms are never
renormalized. Their exact sum must not exceed one, and their complement must agree
with supplied absence within `1e-12`. This exact positive-mass gate is stricter than
the native law's `1e-12` normalization tolerance. For example, the binary floats in
`(0, 0.1, 0.2, 0.3, 0.4, 0, 0)` sum to 1.0 under `math.fsum` but their exact positive
sum exceeds one and refuses. A near-certain player can therefore stop construction
for the whole supplied club rather than have its probabilities adjusted
(`src/squadopt/features/football_phase_coupling.py:144`,
`src/squadopt/features/football_phase_coupling.py:150`,
`src/squadopt/features/football_phase_coupling.py:194`,
`src/squadopt/features/football_flag_inputs.py:280`,
`tests/unit/test_football_phase_coupling.py:78`,
`tests/unit/test_football_phase_coupling.py:219`).

This is an imposed dependence assumption, sensitive to persistent identity
order. It is not learned teammate dependence, a calibrated joint lineup law,
a legal starting XI distribution or a match event generator. Full-match
participation and starting lineup selection remain different inputs. The
receipt identifies the policy as
`persistent_id_circular_positive_role_intervals_v1` and retains the original
seven-atom marginals, native artifact hash, output states and role assignments.
Each state has the floor or ceiling of the coupled expected participant count,
without positional constraints. Identity ordering determines pairwise participation;
this can affect duty pairs such as first and second penalty taker through their
joint absence probability
(`src/squadopt/features/football_phase_coupling.py:3`,
`src/squadopt/features/football_phase_coupling.py:40`,
`src/squadopt/features/football_phase_coupling.py:143`).

The second explicit assumption holds full-club physical, credited goal and
credited assist mass fixed in every state. A state with positive physical mass
and no active player refuses. Positive credited mass without an active
recipient of positive exposure also refuses; no state is discarded or
renormalized to hide missing support
(`src/squadopt/features/football_phase_coupling.py:23`,
`src/squadopt/features/football_phase_coupling.py:173`,
`tests/unit/test_football_phase_coupling.py:135`,
`tests/unit/test_football_phase_coupling.py:186`).

The function checks supplied identity coverage and hash shape. It does not
read source bytes or prove that the roster or marginals belong to that hash.
A caller must bind the actual captured roster and native artifact, retain this
receipt in the projection source, and run the existing projection and native
marginal checks. It must retain the per-player weekly joint law separately;
these within-fixture states do not authorize rebuilding double-gameweek
appearances as independent fixtures
(`src/squadopt/features/football_phase_coupling.py:103`,
`src/squadopt/experiments/football_phase_experiment.py:294`,
`src/squadopt/experiments/football_phase_experiment.py:306`).

The hand-computed two-player example, distinct duration atoms, structural
absence, tiny probabilities and complete forty-player population test the
construction. Those checks establish the stated algebra, not predictive
improvement (`tests/unit/test_football_phase_coupling.py:36`,
`tests/unit/test_football_phase_coupling.py:59`,
`tests/unit/test_football_phase_coupling.py:69`,
`tests/unit/test_football_phase_coupling.py:143`).

These coupling changes cover source-contract tests and receipt/documentation corrections.
They add no runner, accuracy measurement, preregistration or runtime activation.
