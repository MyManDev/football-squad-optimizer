# Benchmark V2 pre-registration

**Status:** pre-registered; no Benchmark V2 measurement has run

**Written:** 2026-08-31

**Owner:** optimization / evaluation

## Question and non-goals

Benchmark V2 asks whether a frozen SquadOpt decision scores better than (a) a
fully feasible ownership template and (b) an honestly selected cohort of strong
real managers when every decision is scored under the same FPL rules.

This protocol does not alter projections, optimization objectives, scenario
generation, calibration, transfer planning, chips, or member-facing output. It
does not add elite-manager behaviour as a prediction feature. The locked 2025-26
holdout is a no-read population.

The existing `ownership_template_rival_v1` measurements remain valid for their
declared comparator: a formation-valid, unconstrained ownership XI and a
most-owned captain under `realized_squad_points_v1`. They are not relabelled as
the average crowd or as a feasible FPL squad.

## Frozen decision and primary scoring policy

A scored decision is

\[
D=(Q,L,B,c,v),
\]

where `Q` contains fifteen distinct players, `L` is an eleven-player starting
line-up, `B` is the ordered four-player bench, `c` is the captain in `L`, and `v`
is a distinct vice-captain in `Q`. Player positions are part of the frozen
decision. The normal-week policy is `official_autosub_captain_v2`.

For realized minutes `m_i` and event points `y_i`, `played_i` is `m_i > 0`.
Automatic substitutions preserve the captured bench order. A goalkeeper can
replace only the starting goalkeeper. An outfield substitute can enter only
where the resulting nominal XI respects DEF 3-5, MID 2-5 and FWD 1-3. A bench
player with zero minutes cannot enter. If no legal playing substitute exists,
the side scores with fewer than eleven players.

If `L*` is the scoring line-up after automatic substitutions, normal-week score
is

\[
\operatorname{score}(D)=\sum_{i\in L^*} y_i + b(D),
\]

with captain bonus

\[
b(D)=
\begin{cases}
y_c & m_c>0,\\
y_v & m_c=0,\;m_v>0,\;v\in L^*,\\
0 & \text{otherwise.}
\end{cases}
\]

The primary score excludes transfer hits and normalizes Bench Boost, Triple
Captain, Free Hit and Wildcard effects out. A separate descriptive reconciliation
may use captured multipliers, active chips and transfer costs to explain an
official entry total; it cannot replace the primary score.

## Historical decision completion

An old optimizer result that did not store bench order and vice-captain may be
completed only from its decision-time projection table:

1. the bench goalkeeper occupies the fixed goalkeeper bench slot;
2. outfield substitutes are ordered by decreasing expected points, then stable
   player id;
3. vice-captain is the non-captain starter with the highest expected points,
   then stable player id.

No realized point, later projection or current live value may complete a frozen
decision. A decision without its decision-time values is `not_evaluable_v2`.

## Constrained ownership template

`ownership_template_v2` selects a complete squad by maximizing

\[
\sum_i \tilde{o}_i x_i
\]

under the configured 15-player position quotas, integer-tenths budget and
three-per-team limit. `o_i` is the decision-time ownership value and
`\tilde{o}_i` its declared deterministic integer scaling. It then chooses a legal
XI maximizing ownership inside that squad. Captain and vice-captain are the two
most-owned starters; outfield bench priority is decreasing ownership. Stable
player id breaks every tie.

This object is a constrained synthetic template, not a real manager and not a
distribution over the crowd. Ownership whose decision-time provenance cannot be
verified is descriptive only.

The V1 feasibility audit reports budget and team-limit violations when the
necessary decision-time price/team data exist. Missing inputs are `not_verified`,
never zero or false.

## Prospective strong-manager cohort

The single strong-manager cohort is `as_of_top_100_v1`. For target gameweek `t`,
membership is the top 100 by rank observable before gameweek `t` outcomes. Their
gameweek `t` picks are read only after its deadline makes them public, and scored
only after settlement. The target list is never chosen using gameweek `t`
results, never reconstructed from end-of-season rank and never backfilled from
rank 101 when an entry is unavailable.

Gameweek 1 has no honest current-season prior ranking and therefore has no
`as_of_top_100_v1` observation. A binding weekly cohort mean requires at least 80
valid entries from the frozen top 100; thinner weeks remain descriptive and carry
`insufficient_coverage`. Raw entry ids and manager names are not committed.

## Paired measurements

For a gameweek with `n_t` valid cohort entries,

\[
\bar S_t^{elite}=\frac{1}{n_t}\sum_{j=1}^{n_t}S_{t,j}^{elite},\qquad
d_t^{elite}=S_t^{system}-\bar S_t^{elite}.
\]

The constrained-template comparison is

\[
d_t^{template}=S_t^{system}-S_t^{template}.
\]

Primary reports use an identical paired-week set. They record mean and median
paired differences, per-season differences, cohort coverage, zero-minute
starters, autosub recovery, vice-captain recovery, bench contribution, V1
feasibility and V1-to-V2 score changes. Missing observations never become zero.

Prospective runs with fewer than eight valid paired gameweeks are descriptive
and `insufficient_evidence`; twelve or more are preferred before a stable-season
interpretation. Existing block-bootstrap utilities may provide diagnostics once
the sample supports them, but no interval changes a preregistered classification.

## Interpretation fixed before results

- A materially smaller V2 template gap identifies comparator/scoring construction
  as part of the old difference.
- A strong constrained template without a matching Top-100 advantage is evidence
  that the synthetic template is not a human-performance proxy.
- A positive Top-100 advantage over SquadOpt identifies a real decision or
  prediction gap.
- A gap concentrated in zero-minute starters and autosub recovery makes
  appearance/minutes the first candidate for the evidence/model phase.
- Missing timing provenance or cohort coverage produces abstention, not success
  or failure.

No numerical improvement threshold is introduced after observing results. This
phase may complete its engineering contract before enough prospective weeks
exist for a statistical conclusion.

## Artifact and execution rules

No binding measurement runs before this document and its implementation are
committed and the complete quality suite passes. Every committed result receives
a `docs/measurements_index.md` row and records repository commit, input snapshot
ids, decision timestamps, policy versions, paired fold ids, exclusions and
coverage. Raw captures remain outside git. The 2025-26 holdout is never loaded,
listed internally, hashed or scored by this protocol.
