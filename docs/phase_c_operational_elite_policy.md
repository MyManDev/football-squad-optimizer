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
An unavailable held player may remain on the bench, as the game permits, but the live
verifier does not allow one in the starting XI.

## Frozen rule

For player `i`, let `m_i` be the control expected-points estimate and let `x_i` be the number
of observed Top-100 managers who selected the player in their previous-gameweek FPL XI.
The handoff must contain all 100 members, so

```text
elite_xi_support_i = x_i / 100
evidence_multiplier_i = 1 + 0.05 * elite_xi_support_i
adjusted_expected_points_i = m_i * evidence_multiplier_i
```

The maximum relative uplift is five per cent. It is a bounded, owner-approved operational
multiplier, not a fitted coefficient and not a probability. A player with zero elite-XI
support is not penalised, preserving room for the point model to identify emerging or
differential picks. The rule may change relative ranking without inventing public
uncertainty.

The following conditions fail closed:

- evidence season, target gameweek or deadline differs from the decision;
- cohort size or observed-member count is not exactly 100;
- any cohort member is missing, or any picked element is unmapped;
- an elite evidence flag is not true;
- count, share and denominator disagree, the XI counts do not sum to `11 * 100`, or a value
  lies outside its support;
- the adjusted projection is missing, negative or non-finite.

A roster player absent from the earlier evidence snapshot receives neutral support and keeps
the control value. Evidence rows for players outside the current roster are ignored. Both
counts are recorded, so ordinary roster churn is visible without making a deadline run
impossible.

The library producer keeps an explicit control-only seam for rollback and replay. The command
line makes Phase C active by default: both artifact paths are required unless
`--control-only` is stated. Supplying only one path is an error. Invalid requested evidence
never falls back silently.

## Identity and rollback

The evidence-aware handoff uses model version `in-season-carry-over-elite-top100-v1` and
feature contract `in-season-carry-over-elite-top100-features-v1`. Diagnostics record both
artifact digests, the policy version, cohort counts, affected-player counts and the applied
projection deltas. The optimizer and public payload continue to receive only expected points.

Rollback is the existing `in-season-carry-over-v1` producer path selected explicitly with
`--control-only`.
Future prospective outcomes may justify a new coefficient or a learned component model, but
must create a new version rather than rewriting this rule after observing its results.

## GW3 producer command

After taking the fresh live capture that the decision will use, produce the handoff with:

```console
python -m scripts.build_projection_handoff \
  --snapshot-id <fresh-live-snapshot-id> \
  --gameweek 3 \
  --evidence-table artifacts/phase_b/player_evidence_v1_2026-27_gw03_top100.csv \
  --evidence-manifest artifacts/phase_b/player_evidence_v1_2026-27_gw03_top100.manifest.json
```

The command reads the handoff back through the consumer, reports the model and evidence
digests, and writes `data/handoffs/2026-27-gw03.json`. The normal gameweek decision command
then consumes that file explicitly:

```console
squadopt gameweek decide \
  --in-season-projection data/handoffs/2026-27-gw03.json
```

The evidence artifact is the sensitivity Top-100 cut from the Top-200 capture. It is approved
for this operational rule but does not replace the frozen Phase A primary cohort and carries
no benchmark or promotion claim. The legacy opening-week recommendation script is not a
mid-season entry point.
