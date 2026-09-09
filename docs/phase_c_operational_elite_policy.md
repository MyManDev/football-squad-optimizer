# Phase C operational elite-evidence policy

Status: one frozen rule, now applied on **two** bases. It was the owner-approved gameweek 3
convention on the legacy in-season blend, and since #395 the same bounded uplift is applied
on the Phase C component base, which is the operational default. The rule itself is
unchanged and stays reproducible and explicit; what changed is what it multiplies, and each
base carries its own model version so a handoff always says which one produced it. The
record used to say the rule "is not combined with the component model"; that stopped being
true when #395 shipped and this document did not move with it. See "Identity and rollback"
below for both identities, and for the boundary in `phase_c_operational_component.md` — which
this combination did not satisfy as that boundary was originally written, and which the owner
amended on 8 September 2026 rather than withdrawing the version.

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
- the evidence artifact was generated after the decision snapshot;
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

The producer applies this rule only when both evidence artifact paths are supplied. Supplying
only one path is an error. Invalid requested evidence never falls back silently. With neither
path, the producer attempts the operational component base; `--control-only` explicitly
selects the legacy in-season control.

Which base the rule lands on is decided before the evidence is read, and is recorded rather
than assumed: the producer builds the component base when the capture carries the settled
live history it needs, and the legacy blend otherwise or on `--control-only`. The uplift is
then applied to whichever base was chosen, the handoff records the base it started from in
`elite_evidence_base_selection`, and `projection_selection` reads `phase_c_component_elite`
or `legacy_elite_candidate` accordingly. On an ordinary mid-season capture with both
evidence paths supplied, that is the component base.

## Identity and rollback

One policy, two identities. On the legacy blend the evidence-aware handoff uses model
version `in-season-carry-over-elite-top100-v1` with feature contract
`in-season-carry-over-elite-top100-features-v1`. On the component base it uses
`phase-c-component-elite-top100-v1` with feature contract
`phase-c-component-elite-top100-features-v1`. Both stamp
`elite_evidence_policy_version = phase_c_operational_elite_policy_v1`, which is this
document, so a decision report that names this policy may be reporting either. Diagnostics
record both artifact digests, the policy version, cohort counts, affected-player counts and
the applied projection deltas. The optimizer and public payload continue to receive only
expected points.

Both identities are listed in `IN_SEASON_CONTROL_MODEL_VERSIONS`
(`squadopt.live.recommendation`), which is where this codebase makes a promotion: the tuple's
own contract says pinning a version there *is* the promotion decision, made in a reviewed
change, and the handoff's `version_is_promoted` is a membership test against it. The
component-elite identity was pinned by #395 and is therefore promoted in that sense.

**What is not satisfied, stated rather than left to a reader.**
`phase_c_operational_component.md` requires that optional Phase B evidence families "must
enter as separately measured candidates". No separate measurement of the uplift on the
component base exists: there is no artifact and no row in `measurements_index.md` for it,
and `phase_c_component_evaluation` — the component base's own evaluation — is descriptive
and promoted nothing. What #395 did satisfy is the same clause's other half: the uplift is
not *silently* multiplied into the component output. It carries its own model version and
feature contract, the contract is enforced at construction, the base it started from is
recorded, `--projection component-only` on the weekly runner and `--control-only` on the
producer opt out, and the decision report states that the rule is an owner-approved evidence
rule and not a calibrated superiority claim. So the position on record is: an owner-approved
operational multiplier of the same governance class as the legacy one, extended to a new
base by a reviewed pin, with the "separately measured candidate" clause **unmet**. That is a
disagreement between two operational records, and it is written down here rather than
resolved by this change.

**How that disagreement was resolved, 8 September 2026.** The owner amended the clause rather
than withdrawing the version. `phase_c_operational_component.md` now carries a second route
into production — a bounded, fitted-nothing multiplier applied after a promoted base — and
the clause requiring a separately measured candidate binds only the fitted route. So the
sentence above is history, not the current rule: as of that date the clause is **amended, not
met**, and the paragraph is kept because the version in production was promoted before the
amendment existed.

This policy is the layered uplift the amendment describes, and the amendment's ten conditions
are read off the mechanism recorded in this document. Nine of them are carried by that
mechanism and are enforced or exercised in code: the composition's own version and feature
contract, both refused at construction unless the evidence fingerprint is present; the uplift
and its digests written into the handoff; the five per cent bound
(`MAXIMUM_RELATIVE_UPLIFT = 0.05`); the never-below-one multiplier; the two capture-time
refusals; the decision binding and the complete-cohort fail-closed list above; the two
opt-outs; the decision report's own wording; and the promotion membership test — with the one
qualification the amendment states under its condition 2, that the handoff's diagnostics block
sits outside the fingerprint. The tenth — that the base is itself promoted — is true of both
bases here but is **not checked anywhere**: `apply_elite_evidence` multiplies whatever base it
is handed, and the producer's `version_is_promoted` tests the composed version, not the base.
Nothing in this change makes that a check.

What the amendment does not give this policy is a measurement. No artifact says what the
uplift does to squad points on the component base, and none is implied by the amendment.

Rollback is the existing `in-season-carry-over-v1` producer path selected explicitly with
`--control-only`, and `--projection component-only` on `scripts.run_week` for the composed
identity. Rolling back the composition means removing its version from
`IN_SEASON_CONTROL_MODEL_VERSIONS`, which is the same reviewed decision in reverse.
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
