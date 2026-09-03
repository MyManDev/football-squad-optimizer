# Phase C operational elite-evidence policy

Status: owner-approved operational convention, frozen before the 2026-27 gameweek 3
outcome. It is active evidence use, not a claim that the candidate is better calibrated or
scores more points than the control.

## Purpose and boundary

The in-season control produces one expected-points value per player. The first operational
Phase C slice lets the deadline-safe Top-100 handoff influence that value while the richer
component model is still being measured. It deliberately does not reinterpret an elite
manager's FPL selection as an appearance probability or a verified real-world start label.
The start component therefore remains unavailable.

Official availability continues to be applied exactly once by the existing live rule after
the handoff is read. The Phase B availability columns are validated as part of the artifact
but are not applied by this policy; applying them here would count the same evidence twice.

## Frozen rule

For player `i`, let `m_i` be the control expected-points estimate and let `x_i` be the number
of observed Top-100 managers who selected the player in their previous-gameweek FPL XI.
The handoff must contain all 100 members, so

```text
elite_xi_support_i = x_i / 100
evidence_multiplier_i = 1 + 0.05 * elite_xi_support_i
adjusted_expected_points_i = m_i * evidence_multiplier_i
```

The maximum relative uplift is five per cent. It is a conservative, versioned product prior,
not a fitted coefficient and not a probability. A player with zero elite-XI support is not
penalised, preserving room for the point model to identify emerging or differential picks.
The rule changes relative ranking without inventing public uncertainty.

The following conditions fail closed:

- evidence season, target gameweek or deadline differs from the decision;
- roster and evidence player identifiers are not exactly equal;
- cohort size or observed-member count is not exactly 100;
- any cohort member is missing, or any picked element is unmapped;
- an elite evidence flag is not true;
- count, share and denominator disagree, or a value lies outside its support;
- the adjusted projection is missing, negative or non-finite.

An evidence artifact is optional at the producer boundary. When neither artifact path is
requested, the old in-season control is reproduced bit for bit. Supplying only one path is an
error. Invalid requested evidence never falls back silently.

## Identity and rollback

The evidence-aware handoff uses model version `in-season-carry-over-elite-top100-v1` and
feature contract `in-season-carry-over-elite-top100-features-v1`. Diagnostics record both
artifact digests, the policy version, cohort counts, affected-player counts and the observed
point deltas. The optimizer and public payload continue to receive only expected points.

Rollback is the existing `in-season-carry-over-v1` producer path with no evidence arguments.
Future prospective outcomes may justify a new coefficient or a learned component model, but
must create a new version rather than rewriting this rule after observing its results.
