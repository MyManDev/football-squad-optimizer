# Phase C operational component model

Status: owner-selected operational default. The historical measurement is descriptive, so this
is a product decision with a reversible rollback, not a claim of confirmatory promotion.

## Decision

For every in-season deadline, the projection producer first attempts model version
`phase_c_control_components_v1` with feature contract
`phase_c_component_form_window_v1`. The model is exactly the component base measured on 147
chronological development folds:

```text
expected_points_i = P(appearance_i) * E(points_i | appearance_i)
```

Appearance is deterministic logistic regression. Conditional minutes and conditional points are
deterministic ridge regressions. Feature order, estimator settings and training seasons are fixed
in the package contract; no deadline run searches hyperparameters.

## Time boundary

The capture stores at most the five event-live documents immediately before the target gameweek.
The target gameweek is never fetched as history. Every historical gameweek must be fully settled
before its minutes and points can become a feature. The live feature builder shifts every rolling
outcome, so a target row cannot read its own result.

Training uses only the declared development seasons 2021-22 through 2024-25. Optional Phase B
elite, ownership, transfer and availability evidence is not part of this model. Those families
must enter as separately measured candidates; the old fixed Top-100 uplift is never silently
multiplied into the component output.

## Fallback and rollback

A player absent from any required historical payload receives the existing in-season estimate for
that player only. Missing is not converted to zero. An older capture carrying none of the bounded
history uses the legacy `in-season-carry-over-v1` handoff and records the missing gameweeks as its
fallback reason. A present but malformed payload fails; only absent or not-yet-final history is an
expected fallback condition.

Operators can request the legacy model explicitly:

```console
python -m scripts.build_projection_handoff --control-only
```

The ordinary command attempts the component model:

```console
python -m scripts.capture_deadline_snapshot
python -m scripts.build_projection_handoff --snapshot-id <fresh-snapshot-id>
```

Diagnostics record the training population, history gameweeks, component/direct-control route
counts, incomplete-player count and component fingerprint. The optimizer still receives only one
expected-points value per player; component probabilities remain internal.
