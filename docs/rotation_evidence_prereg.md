# Rotation evidence evaluation protocol

Status: pre-registered evaluation foundation; no binding candidate measurement has run.
This document changes no arm, gate or live control.

This freezes **what will be read** about the rotation signal, before any number is read.
It names the arms, the target, the population, the eligibility mask, the metrics, the
comparator that decides, which gates apply, and the falsifiers — so that a later reading is
a measurement rather than a choice made after seeing the answer.

It also states the thing that keeps the product and the measurement apart: **none of the
gates below is required to ship the constraint surface.** A gate is needed to claim the
signal *helps*. Offering a member a constraint and pricing it in the solver's own
arithmetic makes no such claim, so this protocol blocks nothing.

## What this document is, and what it is not

Two stages, following the form `phase_c_evaluation_prereg.md` uses.

**This is the foundation.** It freezes the arms, the target and its source, the population,
the eligibility mask, the metrics, the comparator, which of the four gates applies where,
the falsifiers and the exclusions. Where it names a number, that number is **already a
constant in this repository** — `PromotionPolicy.min_mean_improvement` and its confidence
level, `APPEARANCE_LOG_LOSS_EPSILON`, `APPEARANCE_RELIABILITY_BIN_COUNT`. Recording which
existing gate applies is not the same act as inventing a threshold for a candidate.

**A candidate declaration comes later** and names what is genuinely candidate-specific: the
artifact digests, the margin G2 must clear, the gameweek count N a reading waits for, the
coverage fraction C the falsifier fires below, the moving-block length and the seed. The
procedure for that stage is already written in
[`candidate_declaration_review.md`](candidate_declaration_review.md) and is not restated
here; its stop point governs this lane unchanged — **a changed candidate is a new
candidate**, and there is no small-fix exception.

The lane brief this protocol serves asks in one place for every gate number to be written
now and in another for the foundation to name no thresholds. The split above is how both
are honoured: the repository's own constants here, the candidate's own numbers there. If
the lane owner wants a single stage instead, it is this section and the numbers in
[Gates](#gates-and-what-each-licenses) that move, and nothing else.

## Compared arms

Three, and they differ only in what the projection was allowed to read:

- `feed_only_early` — the game feed's own availability fields, from a capture taken about a
  day before the deadline, which is what this loop did through GW3;
- **`feed_only_late`** — the same fields from a capture taken two to three hours before the
  deadline, the lead time the weekly runbook's own policy line names once the lead-time
  change lands (its pull request is open at the time of writing). **This is the control
  that decides.** A signal that does not beat it was an HTTP request, not an API key;
- `feed_plus_rotation` — the same, plus the coded dispositions of `rotation_evidence_v1`.

`rotation` is added to `PHASE_C_EVIDENCE_FAMILIES` as a fifth family name beside `none`,
`availability`, `ownership_transfer` and `elite`. Adding the name is all that is needed:
`phase_c_ablation._pair_exactly` already refuses an arm that changes any paired key or
target column, already refuses one that changes the eligibility mask, and already requires
the candidate to reproduce `component_base` exactly on rows whose `evidence_status` is
`missing`. That last check *is* "absent and zero are different", enforced in code rather
than promised in prose. It is used, not rebuilt.

An arm name is not evidence that the named inputs were used. Every run binds the artifact
versions and their SHA-256 digests, as the Phase C protocol already requires.

## Target and label

**`start_given_appearance`** — the probability that a player started, given that he
appeared. Scored only on rows where `appearance_target == 1`, against `start_target` read
from a settled capture's `stats.starts > 0`.

It is the honest target for three reasons. It isolates rotation from availability *by
construction*, because conditioning on appearance removes the question availability already
answers. `component_metrics.py` already scores it, as `q_start_given_appearance`. And it is
where the skill is actually missing: the lane brief measured a shifted two-gameweek
appearance rate at Brier skill 0.49 on *appearing* and only 0.20 on *starting*.

**Declaring this source and this population is the pre-registration act.**
`features/component_targets.py` says so about its own start label in its module docstring —
*"Declaring a source and a population is a pre-registration act, not something a builder may
do on its own"* — and this document is where that declaration is made for the prospective
season. `START_TARGET_STATUS` remains `unavailable` and
`START_TARGET_SUPPORTED_SEASONS` remains empty for the archive; nothing here changes either,
because nothing here touches the archive.

## Population

Prospective **2026-27** gameweeks only, named by number, from the first week a
`rotation_evidence_v1` artifact exists. A gameweek enters the population when its artifact
and its settled outcome are both on disk, and not before.

Development seasons are **excluded, and not by preference**:
`START_TARGET_SUPPORTED_SEASONS` is empty because the archive adapter maps only columns
present in every supported season and `starts` is not one of them. Every development row
therefore carries no start label at all — the lane brief counts 101,447 of 101,447 — so
there is no development population to score this target on.

The locked 2025-26 holdout is **not loaded, not listed, not hashed and not filtered**. It
appears nowhere in this protocol's population, and a run that reads it is void rather than
caveated.

## Eligibility mask

Rows whose **pre-deadline availability multiplier is exactly 1.0**.

That is where the gap lives, and the mask is the reason the reading can be about rotation at
all: the availability rule prices roughly 485 players a week at exactly one and makes no
distinction among them, of whom about 302 appear and about 86 appear without starting (lane
brief). Below that multiplier the rule has already spoken and the question is not rotation.

Rows outside the mask are **counted and reported, never scored**. A reported exclusion is a
population fact; a silently dropped row is a changed population.

## Metrics

All of them already exist in `evaluation/component_metrics.py`; none is added here.

- **Brier score** on the eligible rows, micro-averaged;
- **log loss**, with probabilities clipped at `APPEARANCE_LOG_LOSS_EPSILON` (1e-06);
- **calibration bias** — mean predicted minus mean realized;
- **reliability bins** — `APPEARANCE_RELIABILITY_BIN_COUNT` (10) fixed equal-width bins.

Four counts are reported **separately and never merged**: population, eligible, scored and
missing. A single "n" hides which of the four moved, and the falsifiers below turn on
exactly that difference.

## The comparator that decides

Not a constant, and not nothing.

The frozen comparator is the **shifted two-gameweek appearance-rate baseline**, which the
lane brief measured at Brier 0.198 against 0.249 for a constant. The question this protocol
asks is whether the coded dispositions beat **that** — not whether they beat a coin. A
candidate that only beats the constant has beaten a baseline nobody proposed.

The baseline is frozen here by description; the candidate declaration binds it by digest.

## Gates, and what each licenses

Four gates, and this table exists so that a passed one is not later read as more than it
is, nor a pending one as a reason to hold the product.

| Gate | Licenses the claim | Does **not** license |
| --- | --- | --- |
| **G0** (ceiling) | "A perfect rotation signal would be worth at least `min_mean_improvement` points per decision as a default exclusion, on the development folds." | Anything about *our* signal. It is an oracle — the ceiling, not the thing. A pass does not make the model good; a fail means chasing a *default projection change* is not worth it, and says nothing about a member-declared constraint. |
| **G1** (free baseline) | "The model tells us something a later HTTP request does not." | Anything about points. A pass means the source is not redundant, nothing more. |
| **G2** (player level) | "The dispositions predict who starts, better than the frozen shifted-appearance baseline, on the eligible mask." | That acting on them earns points. Predicting the label is not the value of the decision, and G2 measures only the first. |
| **G3** (harm check) | Nothing, ever. One-sided; it fires only to stop the lane. | Any positive claim, in any direction, at any sample size available to us. |

The numbers that come from this repository's own constants:

- **G0** uses `PromotionPolicy.min_mean_improvement` (**0.5** points per decision),
  scored under `official_autosub_captain_v2` through
  `evaluation/component_decisions.py`, on the 147 development folds.
- **G2**'s interval is `experiments/statistics.season_aware_moving_block_interval` at
  `PromotionPolicy.confidence_level` (**0.90**), taken on **per-gameweek** paired
  differences. Player rows are not independent bootstrap units, so the unit of inference is
  the gameweek. The margin G2 must clear is candidate-specific and is declared later.
- **G3** is one-sided at **−0.5** points per decision at the decision level, the same
  magnitude in the other direction. It is a stop condition, not a success condition.

**G1 is compared against `feed_only_late`, never `feed_only_early`.** Comparing a signal to
a capture nobody would take again flatters it.

## Why G3 can never promote, said out loud

At the measured paired noise — standard deviation 7.3 to 12.9 net points per week, and
`fw10_holdout`'s 90% interval of [−2.622, 4.000] over 37 folds implying sd ≈ 12 (lane
brief) — this repository's own interval function under its own `PromotionPolicy` gives a
+1 point-per-week effect **0.21 power at 19 weeks, 0.28 at 76, and 0.33 at 152**.

And the failure being targeted is smaller than that. It is 0.51 zero-minute starters per
decision in a setting with **no availability rule at all**, so the live path's rotation
residual is strictly smaller again.

A sub-one-point-per-week effect is therefore not provable at the decision level in four
seasons. This is recorded as a design constraint, not a complaint: it is why the product
does not wait for G3 and never claims what G3 would have licensed.

## Falsifiers, written before any measurement runs

1. **Signal.** *"The model's dispositions carry no information about who starts once the
   shifted appearance rate is in the comparator."* Fires when the eligible-mask Brier of
   `feed_plus_rotation` is not below `feed_only_late`'s by the declared margin, or when the
   90% interval includes zero, after N gameweeks.
2. **Coverage.** *"The model addresses too little of the roster to be measurable."* Fires
   when fewer than the declared fraction C of eligible-mask rows carry a disposition other
   than `not_addressed` — at which point the arm reproduces the control by construction and
   there is nothing left to measure.

N and C are declared in the candidate declaration. Both falsifiers are published whichever
way they fall.

## The third clock is unbounded

Two clocks bound the evidence: `captured_at_utc` bounds the capture and
`generated_at_utc` bounds the artifact, and this repository already refuses evidence whose
either post-dates a decision capture.

A model has a third clock neither covers: what it knew at call time, from training data of
any vintage. **Nothing can bound it, and this protocol does not pretend otherwise.** What
the manifest can do, and must, is record the exact prompt digest, the model identifier and
version, and the digest of every source document quoted — so that *"the claim is traceable
to bytes we captured at time T"* is checkable rather than asserted. The traceability is the
claim; the model's own knowledge cutoff is a stated limit.

## Horizons, honestly

- **G0** — days. It needs no key, no waiting and no new data.
- **G1** — three to four gameweeks to a countable series.
- **G2, directional** — the micro-averaged Brier difference stabilises as a point estimate
  within roughly eight to twelve accumulated gameweeks, so a directional read around GW15.
- **G2, interval-backed** — the unit of inference is the gameweek, so the 90% moving-block
  interval needs closer to fifteen to twenty gameweeks: a defensible verdict around
  GW22-25.
- **G3** — **never.** Not in this season, and not in four.

## Numbers quoted rather than claimed

Some figures above come from the rotation-lane brief (2026-09-08) and **no artifact in this
repository carries them yet**: the 0.49-against-0.20 Brier skill split, the
0.198-against-0.249 baseline comparison, the ~485/~302/~86 weekly mask counts, the
101,447-of-101,447 unlabelled development rows, the 7.3-12.9 sd range with its power
figures, and the 0.51 zero-minute starters per decision. They are cited with their source
because they motivate the design; they are not asserted as this repository's own
measurements. Where a figure comes from a repository constant instead, the constant is named
in place of the number.

## Deliberate exclusions

This work does not fit a model, read a raw capture, create an evidence feature, run a
binding measurement, access the locked holdout, publish any probability, percentage,
quantile or spread on any member-facing surface, change an optimizer objective, modify
`player_evidence_v1`, alter `apply_availability`'s semantics, or apply anything to a
projection. Those are separate responsibilities and separate hypotheses.

No number was read to write this document.
