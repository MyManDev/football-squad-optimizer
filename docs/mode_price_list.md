# The play-mode price list

- Modes: **Garantici** (margin -0.001: a level finish counts), **Agresif** (margin 0: strictly ahead), **Asiri Agresif** (margin +5: clearly ahead). **Saf Puan** is the rival-independent expected-points mode and is the existing control, not re-measured here.
- Same rehearsal throughout: 2024-25, 37 folds, 100 scenarios per fold, `held_out_half` claims, rival = the fold's risk-neutral squad. Gate declared in `docs/mode_price_list_prereg.md` before any number existed.

| Mode | Budget | Behind | Level | Ahead | Ahead >5 | Realized cost | Claimed | Proven |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Garantici | 0.0 | 0.27 | 0.51 | 0.22 | 0.05 | +1.65 | 0.72 | 0.86 |
| Garantici | 2.0 | 0.00 | 1.00 | 0.00 | 0.00 | -0.00 | 1.00 | 1.00 |
| Garantici | 4.0 | 0.00 | 1.00 | 0.00 | 0.00 | -0.00 | 1.00 | 1.00 |
| Garantici | None | 0.00 | 1.00 | 0.00 | 0.00 | -0.00 | 1.00 | 1.00 |
| Agresif | 0.0 | 0.46 | 0.16 | 0.38 | 0.14 | +1.76 | 0.35 | 0.81 |
| Agresif | 2.0 | 0.51 | 0.08 | 0.41 | 0.16 | +2.49 | 0.44 | 0.30 |
| Agresif | 4.0 | 0.49 | 0.16 | 0.35 | 0.22 | +1.11 | 0.42 | 0.03 |
| Agresif | None | 0.41 | 0.22 | 0.38 | 0.16 | +0.11 | 0.43 | 0.00 |
| Asiri Agresif | 0.0 | 0.41 | 0.22 | 0.38 | 0.19 | +1.51 | 0.17 | 0.76 |
| Asiri Agresif | 2.0 | 0.54 | 0.03 | 0.43 | 0.19 | +3.16 | 0.21 | 0.27 |
| Asiri Agresif | 4.0 | 0.49 | 0.05 | 0.46 | 0.22 | +1.97 | 0.22 | 0.05 |
| Asiri Agresif | None | 0.49 | 0.14 | 0.38 | 0.19 | +0.89 | 0.20 | 0.00 |

## The gate, as declared

- **Separation** (Garantici must finish behind less often than Agresif at budget 0, fold-paired, interval clear of zero): difference **-0.189** [-0.297, -0.081] — passes.
- **Direction, Garantici** (lowest pooled P(behind)): passes.
- **Direction, Asiri Agresif** (highest pooled P(ahead by >5)): passes.
- **Honesty** (each held-out claim within ten points of the frequency of the event it claims: ahead+level for Garantici, ahead for Agresif, ahead-by-more-than-five for Asiri Agresif): passes.

**The gate passes: the modes separate, each is best at what its name claims, and the claims are honest.** The selector ships on this evidence, priced against the synthetic rival; re-pricing against the ownership template is the recorded next step.

Known instrument caveat, recorded in `rank_cost_calibration_note.md` and the budget-0 rounding note: at budget 0 the expected-points floor can round above the copy squad, so the Garantici budget-0 cell understates how safe the mode can be.

