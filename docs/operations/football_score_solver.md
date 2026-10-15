# Bounded score fit fallback

Score training first runs the existing bounded L-BFGS-B fit. A finite, well-formed
unsuccessful result with status 2 and unused iteration budget can invoke the separate
coordinate solver. Missing fields, contradictory success/status, nonnumeric coefficients,
out-of-bound coefficients and exhausted iteration budget refuse
(`src/squadopt/prediction/football_score_state.py:692`,
`src/squadopt/prediction/football_score_state.py:700`).

## Same objective, separate numerical certificate

Each score design row is either zero or one of six unit vectors. For coordinate j,
the unchanged negative penalized log likelihood contributes
`A_j * exp(beta_j) - N_j * beta_j + l2 * beta_j**2 / 2`, where A is native weighted
exposure and N is the number of events assigned to that coordinate. Zero-vector
exposures and event log offsets remain in the original objective as constants
(`src/squadopt/prediction/football_score_state.py:188`,
`src/squadopt/prediction/football_score_state.py:271`,
`src/squadopt/prediction/football_score_state.py:296`).

The fallback validates the exact zero/unit-vector design before aggregating it.
It solves each monotone derivative on the existing [-6, 6] bounds by endpoint
conditions or at most 128 bisections. A completely flat coordinate selects zero.
Negative or nonfinite exposures, malformed vectors, mismatched lengths and overflow
refuse. The original penalty, observations and native offsets do not change
(`src/squadopt/prediction/football_score_state.py:296`,
`src/squadopt/prediction/football_score_state.py:335`).

The candidate is then evaluated by the original, unaggregated objective. Its
projected gradient must be at most 1e-8, the same gradient tolerance requested from
the first optimizer. At the lower bound only a negative gradient violates the
condition; at the upper bound only a positive gradient violates it. The existing
raw-gradient metadata field retains its meaning, including a nonzero gradient at
a valid active bound (`src/squadopt/prediction/football_score_state.py:372`,
`src/squadopt/prediction/football_score_state.py:698`,
`src/squadopt/prediction/football_score_state.py:725`).

## Receipt and compatibility

Only fallback fits add a frozen `solver_receipt` through `ScoreSolvedMetadata` or
`ScoreSolvedReplayMetadata`. It records the original failure status and iterations,
six coordinate iteration counts, numerical method and projected-gradient certificate.
The original `optimizer_iterations` still refers to L-BFGS-B. Replay source receipts
and explicit released-season permission remain present
(`src/squadopt/prediction/football_score_state.py:98`,
`src/squadopt/prediction/football_score_state.py:780`,
`tests/unit/test_football_score_solver.py:158`).

Successful legacy fits use the original metadata schema. All candidate metadata
and coefficients are built and integrity-checked before replacing the fitted model,
so a failed refit leaves the previous model intact. The experiment and fixed-fifteen
reader accept both ordinary and fallback replay receipts
(`src/squadopt/prediction/football_score_state.py:737`,
`src/squadopt/prediction/football_score_state.py:799`,
`tests/unit/test_football_score_solver.py:201`,
`tests/integration/test_football_score_state_experiment.py:49`).

The tests establish numerical and serialization behavior using invented records.
They include analytic unpenalized roots, both active bounds, an independent dense
penalized objective, malformed optimizer results and failed-refit atomicity.
They do not establish predictive improvement or activation
(`tests/unit/test_football_score_solver.py:1`,
`tests/unit/test_football_score_solver.py:51`,
`tests/unit/test_football_score_solver.py:64`,
`tests/unit/test_football_score_solver.py:201`).
