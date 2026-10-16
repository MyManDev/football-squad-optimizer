# Source missingness for the experimental club unit model

Use the explicit `source_all_unobserved_residual_v2` policy to represent a player
whose entire declared source profile is unobserved once per source and FPL scoring
position. The default remains `per_attribute_v1`. The new policy declares model
version `football_projected_unit_source_missingness_v2` and feature version
`reference_relative_unit_source_missingness_v2`.
(`src/squadopt/prediction/football_unit_strength.py:52`,
`src/squadopt/prediction/football_unit_strength.py:343`)

## Feature meaning

For each logical source identity and scoring position, the new policy uses the
following counts and sums divided by eleven:

1. One count of players with no observed value among that source's declared
   attributes. This describes observed values, without assuming that the player
   has or lacks an FM UID.
2. The existing sum of observed numeric values for each attribute.
3. For each attribute, a residual missing count restricted to players with at
   least one observed declared attribute from the same source.

Source groups use the attribute contract's source identities. An observed zero
is observed; an absent profile and an explicit all-`None` profile have the same
missingness meaning. Values remain unfilled. Player identity, position count and
venue interaction features retain their existing roles.
(`src/squadopt/prediction/football_unit_strength.py:92`,
`src/squadopt/prediction/football_unit_strength.py:110`,
`src/squadopt/prediction/football_unit_strength.py:202`,
`tests/unit/test_football_unit_source_missingness.py:78`,
`tests/unit/test_football_unit_source_missingness.py:118`,
`tests/unit/test_football_unit_source_missingness.py:157`)

This representation addresses a specific prior dependence. The legacy feature
builder creates one missing count per attribute, followed by train-only scaling
and an L2-regularized Poisson fit. If a source's attributes are always missing
together, their standardized missing columns are identical. For `n` identical
columns and a fixed aggregate coefficient `B`, equal coefficients minimize their
squared penalty at `n * (B / n)^2 = B^2 / n`. Repeating the same absence signal
therefore changes its effective penalty. The new source count removes that
particular repetition. Other trait correlations and limited observations still
require assessment; this change does not establish predictive improvement.
(`src/squadopt/prediction/football_unit_strength.py:749`,
`src/squadopt/prediction/football_unit_strength.py:683`,
`src/squadopt/prediction/football_unit_strength.py:699`,
`tests/unit/test_football_unit_source_missingness.py:133`)

## Fit and retain the version

```python
model = FootballUnitStrengthModel(
    observations,
    cutoff=fit_cutoff,
    allow_released_2025_26=True,
    missingness_policy="source_all_unobserved_residual_v2",
)
```

The released-season argument remains explicit. The fitting offset, train-only
scaler, fixed regularization `alpha=0.1` and Poisson objective are unchanged. Keep
the original training observations and source receipts, and record a new actual
fit cutoff for this model version. Historical replay and current projection
continue to use their separate input contracts.
(`src/squadopt/prediction/football_unit_strength.py:343`,
`src/squadopt/prediction/football_unit_strength.py:653`,
`src/squadopt/prediction/football_unit_strength.py:683`,
`src/squadopt/prediction/football_unit_strength.py:699`,
`src/squadopt/features/football_unit_inputs.py:800`)

Result metadata records the policy, source attribute groups and both missingness
definitions. The experiment boundary reconstructs the expected feature columns
and refuses mismatched versions, groups, meanings or regularization. One component
artifact must use one declared unit model version. Every attribute source family
must match both current and historical source receipts. Reference neutrality and paired
reversal remain required; the new policy retains the existing independent native
focal minute law.
(`src/squadopt/prediction/football_unit_strength.py:889`,
`src/squadopt/prediction/football_unit_strength.py:965`,
`src/squadopt/experiments/football_unit_experiment.py:410`,
`src/squadopt/experiments/football_unit_experiment.py:643`,
`src/squadopt/experiments/football_unit_experiment.py:780`,
`tests/unit/test_football_unit_source_missingness.py:179`,
`tests/unit/test_football_unit_source_missingness.py:253`)

Default and explicitly selected legacy models retain the frozen serialized
metadata digest. Tests also compare one versus 47 declared attributes when all
numeric features are zero and only source absence changes, so duplicate trait
declarations do not change the new absence prior.
(`tests/unit/test_football_unit_source_missingness.py:133`,
`tests/unit/test_football_unit_source_missingness.py:208`)
