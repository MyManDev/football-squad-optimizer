# The windowed claim works, and it inflates — for a reason the numbers already knew

`windowed_rank.md` and `mode_plan_selection.md` are the first end-to-end runs of the
window machinery: joint paths → one ScenarioSet per window → the unchanged rank objective →
P(ahead of the crowd), and then a menu of transfer-and-chip plans picked per play mode.
The machinery works. The *claims* it produces against the crowd do not survive contact
with what actually happened, and the failure is systematic, not noise:

| Horizon | Windows | Mean claimed P(ahead) | Realized ahead |
| ---: | ---: | ---: | ---: |
| 1 | 5 | 0.89 | 0.60 |
| 3 | 5 | 0.97 | **0.00** |
| 5 | 5 | 0.99 | **0.00** |

## Why, precisely

Two facts already measured in this repository collide here:

1. The scenario generator centres every player on **the control's own projection** — its
   location calibration is against realized outcomes *of the whole pool*, and it holds.
2. The crowd's eleven **outperforms the control's best squad by +7.19 points a week**
   ([template_rival_strength](template_rival_strength.md)): ownership carries information
   the control's projection does not — team news, form, fixtures priced by humans.

So inside the scenarios, the crowd is just eleven players priced at the control's
expectations, and beating it looks easy; in reality it scores about seven points a week
above those expectations. Over one week the gap is sometimes overcome (0.60 realized);
over three or five weeks a ~7-point-a-week bias compounds to ~21–35 points, and the
claimed probability becomes fiction. `held_out_half` cannot fix this — both halves are
drawn from the same crowd-blind distribution. The single cell of the earlier full-pool
run (claimed 1.00, realized behind) was the same effect at its extreme.

**The rule this measurement buys:** a rival-aware probability is only as honest as the
rival's representation inside the scenarios. Against the *risk-neutral* rival the claims
are honest (`rank_cost_calibration`: claimed 0.35–0.44 vs realized 0.35–0.41) because that
rival really is priced by the projection. Against the *crowd* they are not, until the
crowd's measured edge enters the scenario model — as a rival-side location term, with
+7.19 [+2.35, +11.97] as its first estimate. That is scheduled follow-up work, gated like
everything else; until it lands, windowed claims against the template are reported with
this note attached, and the product must not show them as probabilities.

## What the mode-selection run showed meanwhile

One window (2024-25 GW20, horizon 3), one held squad, a menu of eight candidate plans
(no chips, the planner's choice, every forced BB/TC placement), all priced on the same
paths, each mode picking from the same menu — the whole flow in **~7 minutes** wall clock:

- **Saf Puan** picked `planner_choice` (both chips, highest expected window score, 341.6).
- The three competitive modes all picked `3xc_gw20`: with the crowd under-priced, every
  chip plan showed P(success) ≈ 1.00, the tie broke toward fewer chips — the declared
  tie-break doing its job — and the modes could not meaningfully disagree.

So the selector's arithmetic is correct and its inputs are not yet honest enough for the
competitive modes to separate against the crowd. The two fixes are the same fix: put the
crowd's edge into the scenarios, then re-run this selection and expect Garantici to stop
seeing 1.00 everywhere.

## What stands regardless

- The window bridge is exact at horizon one (fingerprint-equal, tested), so nothing about
  single-week claims changed.
- The candidate menu, the per-scenario chip arithmetic (TC ×3, BB bench, hits charged),
  and the mode targets are all unit-tested independently of any scenario model.
- Wall clock: a full window selection fits comfortably inside the five-minute live budget
  once the pool rule is applied; the first full-pool attempt did not, and the pool rule
  (best-per-position + cheapest-per-position + the rival's eleven) is now part of the flow.


---

## Update, 2026-08-20: the edge term is in, and it does what was gated — no more

`rival_edge_prereg.md` declared the gate before the change existed; the change landed the
same day (the `rival_edge_points` parameter at all four places a rival is scored — the rank
solver, the fixed-decision comparison, the goal menu, and the plan selector's window
scores; zero-edge identity is proven bit-for-bit by test).

Re-run with the measured edge (+7.19 a week):

| Horizon | Claimed (no edge) | Claimed (edge) | Realized |
| ---: | ---: | ---: | ---: |
| 1 | 0.89 | **0.77** | 0.60 |
| 3 | 0.97 | **0.87** | 0.00 |
| 5 | 0.99 | **0.89** | 0.00 |

The gate asked for deflation — the claims must move toward the realized outcomes and the
horizon-one gap must not widen — and that passed. What it deliberately did not ask for is
calibration, and the numbers say why: 0.87 against a realized 0.00 is still fiction. A
constant per-week edge removes the part of the inflation the crowd's *average* advantage
explains; it cannot remove the part that comes from my own squad's selection optimism on
the same scenarios, from the edge's week-to-week variance, or from five windows being five
windows. Windowed crowd-relative claims therefore still ship as *diagnostics*, not
probabilities, and the product rule from the first half of this note stands unchanged.

What the edge did unlock is the thing the mode selector needed: the competitive modes now
**separate on the plan menu**. Yesterday every chip plan sat at P≈1.00 against the
under-priced crowd and the tie-break decided everything; with the edge in, Garantici and
Agresif pick the single-chip `bboost_gw21` (P(success) 1.00, with the 3xc placements
falling to 0.97–0.98 and `no_chips` to 0.92), while Aşırı Agresif pays for both chips
(`planner_choice`) because only the biggest swing clears a five-point margin against an
edged crowd. Saf Puan ignores the rival by construction and keeps `planner_choice`. One
window, so this is an observation, not evidence — but it is the first time the four modes
have disagreed for their stated reasons.
