# Phase C operational component model

Status: owner-selected operational default. The historical measurement is descriptive, so this
is a product decision with a reversible rollback, not a claim of confirmatory promotion.

The evidence boundary stated under "Time boundary" was **amended by the owner on 8 September
2026**. The original wording is left in place and the amendment is a separate section below;
read both, in that order, before relying on either.

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

**Where that boundary stands today.** The model above is unchanged: no evidence family is
fitted into it. But since #395 the bounded Top-100 uplift is applied *on top of* this base
whenever the producer is given both evidence artifact paths, which on an ordinary mid-season
capture is the default weekly path. The "never silently" half of the boundary holds — the
composition is a separate model version, `phase-c-component-elite-top100-v1`, with its own
feature contract enforced at construction, its base recorded in the handoff, an opt-out on
both runners and a decision report that names the rule. The "separately measured candidate"
half does **not**: no measurement of the uplift on this base exists, and no row in
`measurements_index.md` describes one. That is recorded here rather than argued away, and
`phase_c_operational_elite_policy.md` carries the same statement beside both identities.
Nothing in that record changes this model or its rollback.

**That was the position until 8 September 2026.** On that date the owner amended the rule
rather than withdrawing the version, and the next section is what binds from then on. The
two paragraphs above are left exactly as they were written, because the version now in
production was promoted under the rule *as written* and did not meet it. Anyone asking
whether the shipped model cleared the rule it was promoted under gets the answer here: it
did not.

## Amendment, 8 September 2026 — layered uplifts

### What is being amended, and why the record says so plainly

The clause above requires that optional Phase B evidence families "must enter as separately
measured candidates". `phase-c-component-elite-top100-v1` did not satisfy it. #395 pinned
that version into `IN_SEASON_CONTROL_MODEL_VERSIONS` (`squadopt.live.recommendation`), which
is where this codebase makes a promotion, and it decides live squads on an ordinary
mid-season capture. No measurement of the Top-100 uplift on the component base exists: no
artifact, no row in `measurements_index.md`, and `phase_c_component_evaluation` measured the
bare base and promoted nothing.

Two ways out were available: withdraw the version, or amend the rule. **The owner amended the
rule.** This is not a finding that the old rule was met. It is a decision that the old rule
was wrong to treat every route into production as the same route, taken with the knowledge
that the model in production is the reason the question came up. The cost of choosing this
way round is stated at the end of this section rather than left out of it.

### The amended rule

Optional Phase B evidence may reach production by exactly two routes.

**Route 1 — a fitted evidence family.** Unchanged, and still the only route for anything that
learns from the evidence. A family that enters the model — as a feature, a coefficient, a
weight, a per-player or pooled fit of any kind — must enter as a separately measured
candidate, under its own pre-registration, against the component base, on the declared folds.
Nothing below relaxes this.

**Route 2 — a layered uplift.** A fixed, owner-approved multiplier applied *after* a promoted
base, fitting nothing, may enter without its own candidate measurement **if and only if every
one of the following holds.** Each condition is a protection the code carries today, verified
by reading it and cited where it is enforced; a condition that names a number takes that
number from the code.

1. **It is named in the model version, and the name is fingerprinted.** The composition
   carries its own model version and its own feature contract —
   `phase-c-component-elite-top100-v1` and
   `phase-c-component-elite-top100-features-v1` (`COMPONENT_ELITE_MODEL_VERSION`,
   `COMPONENT_ELITE_FEATURE_CONTRACT_VERSION` in `squadopt.prediction.elite_evidence`) — and
   never reuses the base's version. `InSeasonProjection.__post_init__` refuses that version
   unless the feature contract is exactly that one *and* an evidence fingerprint is present,
   and it forbids the un-uplifted versions from carrying an evidence fingerprint at all. Both
   the version and the evidence fingerprint are inside the handoff's own fingerprint, so an
   edited handoff is refused on read (`read_projection_handoff`).
2. **The uplift is visible in the handoff.** The written file carries the model version, the
   feature contract, the 64-character evidence fingerprint, and diagnostics naming the policy
   version, the cohort size, the maximum uplift, how many players were lifted, the mean and
   maximum point deltas, and both artifact digests. `elite_evidence_base_selection` records
   which base the uplift landed on and `projection_selection` reads `phase_c_component_elite`.
   **Precisely, and against this rule's own interest:** the version, contract and evidence
   fingerprint are covered by the handoff fingerprint, but the diagnostics block is not, and
   `read_projection_handoff` only compares the recorded fingerprint when the file still has
   one — a handoff with its `fingerprint` field deleted is read without that check. So the
   uplift is visible and its identity is tamper-*evident* against edits, not tamper-proof.
3. **Its magnitude is bounded, and the bound is five per cent.** `MAXIMUM_RELATIVE_UPLIFT` is
   `0.05`. The multiplier is `1 + 0.05 * count/100` with the count validated as an integer in
   `[0, 100]`, so it lies in `[1.00, 1.05]` and no projection can move by more than five per
   cent of itself. A layered uplift whose bound is not stated as a constant in the code, or
   which cannot be shown to lie inside a stated interval, does not qualify.
4. **It cannot penalise.** The multiplier is never below one: a player with no elite support,
   and a roster player absent from the evidence entirely, keeps the base value unchanged. A
   two-sided or negative multiplier is not a layered uplift under this rule.
5. **It refuses evidence that post-dates the decision capture, on both clocks.**
   `apply_elite_evidence` rejects the run if the evidence rows' `captured_at_utc` is later
   than the decision snapshot, *and* separately if the artifact's `generated_at_utc` is later.
   The second clock is the one that matters in practice: re-exporting evidence for a capture
   already taken always stamps the artifact after it, which `run_week`'s
   `check_evidence_for_reused_capture` states before a capture is spent rather than after.
6. **It is bound to the decision it is used for, and fails closed.** Season, target gameweek
   and deadline in the evidence must each be a single value equal to the decision's. The
   cohort must be exactly 100 declared and 100 observed with no missing member picks and no
   unmapped elements; every row must carry an observed-evidence flag; the XI counts must sum
   to `11 * 100 = 1100`; each share must equal its count over 100 to within `1e-12`; base
   points must be present, finite and non-negative, and so must the adjusted points. Any one
   of these raises rather than degrading to a silent fallback. Supplying one of the two
   evidence paths without the other is an error, not a run without evidence.
7. **It layers on a base that is itself promoted.** Both bases the producer can build —
   `phase_c_control_components_v1` and the legacy `in-season-carry-over-v1` — are pinned in
   `IN_SEASON_CONTROL_MODEL_VERSIONS`, so this holds today. **It holds by construction, not by
   a check:** nothing in `build_projection_handoff` or `apply_elite_evidence` tests the base's
   promotion before multiplying, and `version_is_promoted` in the producer's report is a
   membership test on the *composed* version, not on the base. This condition is therefore a
   requirement on whoever adds a base, and is not enforced for them. It is written as a
   condition anyway, because that is what it is; the missing check is recorded as a gap rather
   than reported as a protection.
8. **It is reversible without a rebuild, from either runner.**
   `build_projection_handoff --control-only` selects the legacy base and
   `run_week --projection component-only` leaves the uplift out; removing the version from
   `IN_SEASON_CONTROL_MODEL_VERSIONS` withdraws it, which is the same reviewed decision in
   reverse.
9. **It is stated wherever its numbers are read.** The decision report prints, for this model
   version, that the projection carries the bounded Top-100 adjustment on the component base,
   that it is an owner-approved evidence rule and "not a calibrated superiority or probability
   claim", and the policy version beside it (`squadopt.live.report`). The member-facing window
   publishes the uplift sentence only when the handoff actually carries an evidence
   fingerprint (`window_stated_limits`), so the claim is read off the file rather than assumed.
10. **It is promoted by a reviewed pin, and by nothing else.** Adding the version to
    `IN_SEASON_CONTROL_MODEL_VERSIONS` is the promotion decision; `verify_decision` and
    `plan_horizon` refuse a handoff whose model version is not in that tuple, and the producer
    prints a refusal warning when it writes one that is not.

A layered uplift satisfying all ten enters production with no measurement of its own. It
enters as what it is — an owner-approved operational multiplier — and never as a measured
improvement.

### What the amended rule still forbids

A rule that forbids nothing is not a rule. These are the things this one fails:

- **Anything fitted.** A coefficient, weight or threshold learned from the evidence, however
  small, is Route 1 and needs its own measured candidate. The five per cent here is approved,
  not estimated, and a future rule that wants a *fitted* uplift gets no cover from this one.
- **A second family layered this way.** Route 2 is spent by this one rule on this one family.
  Ownership, transfer movement and availability do not inherit it; each would be a new owner
  decision under this rule's conditions, and availability in particular is already applied
  once elsewhere, so layering it here would double-count.
- **Stacking.** Two uplifts multiplied onto one base is not covered, whatever each one's
  bound. The composed version names one uplift and the bound is stated for one.
- **An unnamed or unbounded uplift.** No version of its own, no feature contract of its own, a
  bound that is not a constant in the code, a bound wider than five per cent, or a multiplier
  that can go below one — each fails on its own.
- **A silent base change.** Layering on a base that is not pinned in
  `IN_SEASON_CONTROL_MODEL_VERSIONS`, or on a base the handoff does not record.
- **Late or partial evidence.** Evidence captured or generated after the decision capture, a
  cohort short of its declared 100, a member with unreadable picks, or an artifact that
  disagrees with its own denominator — all fail closed, and a fallback that quietly drops the
  evidence instead is forbidden too.
- **Any claim that it is better.** No report, artifact or member-facing surface may state or
  imply that the uplift improves accuracy or squad points. Nothing has measured that.

A worked example of a failure, so the rule is not abstract: a proposed ownership uplift
bounded at eight per cent, reusing the component base's own feature contract, would fail
conditions 1, 3 and the second and fourth bullets above, and would need Route 1 or a fresh
owner decision.

### What this amendment costs

A separately measured candidate — the thing this rule now waives — is the `component_plus_elite`
arm of `phase_c_evaluation_prereg.md`, scored against `component_base` on identical keys,
decisions and optimizer settings. Not having run it, we do not know:

- the **sign and size** of the uplift's effect on realized squad points against the component
  base, paired decision by decision, and whether that sign is stable across weeks;
- **how often it changes a decision at all** — whether the players it lifts are ones the base
  already ranked into the XI, or ones it did not, and what it does to the captain choice;
- whether **five per cent is anywhere near the right size**: the measured incremental value of
  lagged elite XI support could be near zero, or several times this;
- **where any effect sits** — by position, price band and fixture count — which is what would
  say whether the rule helps differentials or merely re-ranks the already-obvious.

None of that is known, and this document does not claim it. What is known is only what the
bound guarantees: no projection moves by more than five per cent of itself, and none moves
down. `phase_c_component_evaluation` measured the base **without** the uplift, so its numbers
are not evidence for the uplift and must not be cited as if they were.

**The measurement is not merely skipped; it is not currently available, and that is the real
cost.** This family cannot be measured on the development folds: the archive holds no
deadline-valid Top-100 cohort captures for 2021-22 through 2024-25, so
`phase_c_evaluation_prereg.md` records that promotion against the current operational control
"requires matched prospective decisions because its deadline-frozen Top-100 input does not
exist historically", and `phase_c_component_evaluation` records elite incremental-value claims
as prospective for the same reason. So the price of this amendment is not one skipped run. It
is that the uplift now decides real squads while the only evidence that could ever price it —
a prospective, week-by-week record built from live captures — has not been accumulated, and
the amendment removes the pressure to accumulate it.

Nothing currently accumulates it. Each handoff records `elite_evidence_players_uplifted` and
the mean and maximum point deltas for its own week, and no artifact, index row or runner reads
those back; there is no series and no comparator. Building one is a separate decision this
amendment does not take and does not require. Until it is taken, "unmeasured" here means
unmeasured indefinitely, not unmeasured yet.

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
