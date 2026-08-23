# Rival calibration: the resampled edge against what happened

- Cells: 393 over 4 seasons; 200 scenarios per window.
- Season S resamples only the other seasons' measured weekly edges (leave-one-season-out); the constant baseline is the same pool's mean.

| h | cells | claimed (sampled) | claimed (constant) | realized | gap | 90% CI | clause |
| ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | 139 | 0.763 | 0.841 | 0.345 | +0.417 | [+0.349, +0.485] | fails |
| 3 | 131 | 0.869 | 0.933 | 0.321 | +0.549 | [+0.477, +0.616] | fails |
| 5 | 123 | 0.903 | 0.955 | 0.293 | +0.610 | [+0.542, +0.681] | fails |

**Verdict: fails** (clauses 3-4 as declared; clause 5 — mode-ordering stability — runs separately).

- Measurement only. The locked 2025-26 holdout is refused by the development season list; nothing consumes this result until the full gate says so.
