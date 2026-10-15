# Joint participation for phase allocation

`couple_phase_minutes` constructs bounded phase states from a complete supplied
club roster and seven native atoms per player: absence, three start minute bins
and three cameo minute bins. It preserves the distinct durations of the start
and cameo atoms (`src/squadopt/features/football_phase_coupling.py:22`,
`src/squadopt/features/football_phase_coupling.py:91`,
`tests/unit/test_football_phase_coupling.py:57`).

The policy sorts persistent player identities and concatenates their six
positive probability intervals around a unit circle. Each player's remaining
arc is absence. Splitting at all endpoints gives at most `6*N+1` states; the
population limit of 170 keeps this inside the existing 1,024-state cap.
Endpoint comparisons use exact fractions of the supplied binary floats, so
small positive intervals are not silently discarded. Positive atoms are never
renormalized. Their complement must agree with supplied absence within `1e-12`
(`src/squadopt/features/football_phase_coupling.py:91`,
`src/squadopt/features/football_phase_coupling.py:132`,
`src/squadopt/features/football_phase_coupling.py:173`,
`tests/unit/test_football_phase_coupling.py:75`).

This is an imposed dependence assumption, sensitive to persistent identity
order. It is not learned teammate dependence, a calibrated joint lineup law,
a legal starting XI distribution or a match event generator. Full-match
participation and starting lineup selection remain different inputs. The
receipt identifies the policy as
`persistent_id_circular_positive_role_intervals_v1` and retains the original
seven-atom marginals, native artifact hash, output states and role assignments
(`src/squadopt/features/football_phase_coupling.py:2`,
`src/squadopt/features/football_phase_coupling.py:34`).

The second explicit assumption holds full-club physical, credited goal and
credited assist mass fixed in every state. A state with positive physical mass
and no active player refuses. Positive credited mass without an active
recipient of positive exposure also refuses; no state is discarded or
renormalized to hide missing support
(`src/squadopt/features/football_phase_coupling.py:18`,
`src/squadopt/features/football_phase_coupling.py:161`,
`tests/unit/test_football_phase_coupling.py:127`).

The function checks supplied identity coverage and hash shape. It does not
read source bytes or prove that the roster or marginals belong to that hash.
A caller must bind the actual captured roster and native artifact, retain this
receipt in the projection source, and run the existing projection and native
marginal checks. It must retain the per-player weekly joint law separately;
these within-fixture states do not authorize rebuilding double-gameweek
appearances as independent fixtures
(`src/squadopt/features/football_phase_coupling.py:91`,
`src/squadopt/experiments/football_phase_experiment.py:294`,
`src/squadopt/experiments/football_phase_experiment.py:306`).

The hand-computed two-player example, distinct duration atoms, structural
absence, tiny probabilities and complete forty-player population test the
construction. Those checks establish the stated algebra, not predictive
improvement (`tests/unit/test_football_phase_coupling.py:34`,
`tests/unit/test_football_phase_coupling.py:57`,
`tests/unit/test_football_phase_coupling.py:67`,
`tests/unit/test_football_phase_coupling.py:135`).
