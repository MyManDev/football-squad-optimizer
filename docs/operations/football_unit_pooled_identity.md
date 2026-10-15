# Unit player residual pooling

Select `identity_policy="raw_identity_pooled_no_home_v1"` only with physical
exposure and source missingness v2. It creates
`football_projected_unit_pooled_identity_v4`; the default remains
`exposure_standardized_v1`, preserving earlier versions
(`src/squadopt/prediction/football_unit_strength.py:52`,
`src/squadopt/prediction/football_unit_strength.py:342`,
`src/squadopt/prediction/football_unit_strength.py:362`).

Player presence differences retain their raw values of minus one, zero or one.
Their applied scale is exactly one. Shared FM, position and source missingness
features retain the training exposure weighted standard deviations without
centering. Player by home interaction columns are absent; shared home columns
remain. Observed scaler statistics and applied feature scales are stored
separately (`src/squadopt/prediction/football_unit_strength.py:132`,
`src/squadopt/prediction/football_unit_strength.py:591`,
`src/squadopt/prediction/football_unit_strength.py:675`).

For goals `y_i`, physical causal offset `e_i`, shared features `z_i`, raw identity
differences `d_i`, and `W=sum(e_i)`, the declared objective is:

```text
eta_i = z_i beta + d_i u
J = sum(e_i exp(eta_i) - y_i eta_i) / W
    + 0.1 / 2 * (squared_norm(beta) + squared_norm(u))
```

The code passes `y_i/e_i` with sample weight `e_i` to the same Poisson head,
without an intercept and with fixed alpha 0.1
(`src/squadopt/prediction/football_unit_strength.py:654`,
`src/squadopt/prediction/football_unit_strength.py:687`). The loss convention is
the sample weight normalized objective in the
[official sklearn implementation](https://github.com/scikit-learn/scikit-learn/blob/1.9.0/sklearn/linear_model/_glm/glm.py).
Consequently the equivalent raw identity Gaussian MAP precision on the
unnormalized count likelihood scale is `0.1*W`. The result records both `W` and
that precision (`src/squadopt/prediction/football_unit_strength.py:57`,
`src/squadopt/prediction/football_unit_strength.py:904`). It does not claim that
alpha 0.1 is an absolute Bayesian prior precision or that posterior uncertainty
was estimated.

This is exposure dependent regularization toward zero identity residual around
the shared prediction. Under the former standardized identity representation,
a raw effect `theta` had a penalty proportional to `variance*theta^2`; rare
presence therefore received less penalty in raw log rate units. The new policy
uses the same penalty for every raw identity effect. A local scalar quadratic
approximation gives pooling factor `I/(I+0.1*W)`, where
`I=sum(e_i exp(eta_i)d_i^2)`. This is a derivation of the displayed objective,
not an exact multivariate uncertainty estimate. The synthetic matched rate
test verifies that less exposure produces stronger shrinkage, and a separate
test independently reconstructs its normalized gradient
(`tests/unit/test_football_unit_pooled.py:104`,
`tests/unit/test_football_unit_pooled.py:114`).

FM traits and player indicators can describe overlapping directions. The
positive L2 penalty gives a unique penalized solution, while its decomposition
does not establish separately identified causal player abilities. Shared
correlated trait columns retain their existing coordinate prior. If a direction
were represented by several identical columns, splitting an effect across them
would reduce its aggregate L2 penalty. V4 does not select a correlation cutoff,
remove traits or calibrate a source family covariance. Shared values and their
scales have a regression check against physical v3
(`tests/unit/test_football_unit_pooled.py:165`). Missing source attributes still
have absence and residual missingness fields; unseen players receive no fitted
identity residual (`tests/unit/test_football_unit_pooled.py:178`,
`tests/unit/test_football_unit_pooled.py:217`).

Actual intervals remain the training observations. Splitting one unchanged
feature interval preserves its total offset and goals and cannot manufacture
additional support (`tests/unit/test_football_unit_pooled.py:131`). Distinct
fixture count, actual seconds and contrast exposure should be reported
separately when inspecting a real fit. Applying a point XI to a whole fixture
still assumes its learned interval rate association persists for that exposure;
this policy does not establish a learned joint lineup law or a substitute to
starter causal effect. The existing physical offset and prediction semantics
remain explicit (`src/squadopt/prediction/football_unit_strength.py:66`,
`src/squadopt/prediction/football_unit_strength.py:74`).

The strict result boundary checks model, feature, prior and scaling identities,
the exact identity column set, positive observed/applied scales, scale one for
identity columns, unchanged shared scales and the `alpha*W` relation. Older
versions refuse new pooling claims. The existing physical source replay and
partition checks remain on the result path
(`src/squadopt/experiments/football_unit_experiment.py:424`,
`src/squadopt/experiments/football_unit_experiment.py:477`,
`tests/unit/test_football_unit_pooled.py:264`). Neutral reference, paired
reversal, pickle and legacy metadata parity are covered
(`tests/unit/test_football_unit_pooled.py:182`,
`tests/unit/test_football_unit_pooled.py:297`).

This policy is distinct from the measured final point position mean shrinkage
grid, which made no promotion (`docs/shrinkage_grid.md:3`,
`docs/shrinkage_grid.md:26`). It leaves the rejected stationary role transition
and full match clean sheet replacement outside this change
(`docs/research/football_candidate_results.md:31`,
`docs/research/football_candidate_results.md:52`). Implementation and fit
receipts do not establish measured benefit
(`docs/research/README.md:92`).
