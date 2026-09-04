# Strategy screening: the overlap knobs

- Contract: `strategy_screening_v1`; pre-registered in `strategy_screening_prereg.md` before the run
- Population: {'seasons': ['2021-22', '2022-23', '2023-24', '2024-25'], 'origins': [5, 15, 25, 33], 'horizon': 1, 'declared_folds': 16, 'built_folds': 16, 'control_proven_folds': 16}
- The locked holdout was not accessed by this run.

## `ortak-koru` — knob `overlap_floor` (default 9)

| Level | Proven share | Mean E[pts] | Mean cost | Δ vs default | 90% CI | Moves |
| ---: | ---: | ---: | ---: | ---: | --- | --- |
| 6 | 1.000 | +90.030 | +0.719 | +6.001 | [+4.114, +7.439] | True |
| 7 | 1.000 | +89.421 | +1.328 | +5.392 | [+3.535, +6.804] | True |
| 8 | 1.000 | +87.235 | +3.514 | +3.206 | [+1.907, +4.307] | True |
| 9 | 1.000 | +84.029 | +6.720 | - | - | - |
| 10 | 0.688 | +78.318 | +11.676 | -7.097 | [-8.553, -4.970] | False |
| 11 | 0.125 | +80.125 | +10.042 | -8.125 | [-8.125, -8.125] | False |

**Verdict: `search`** — by the pre-registered rule.

## `fark-yarat` — knob `overlap_ceiling` (default 5)

| Level | Proven share | Mean E[pts] | Mean cost | Δ vs default | 90% CI | Moves |
| ---: | ---: | ---: | ---: | ---: | --- | --- |
| 3 | 1.000 | +90.315 | +0.434 | -0.409 | [-0.688, -0.153] | True |
| 4 | 1.000 | +90.640 | +0.109 | -0.084 | [-0.169, +0.000] | False |
| 5 | 1.000 | +90.724 | +0.025 | - | - | - |
| 6 | 1.000 | +90.749 | +0.000 | +0.025 | [+0.000, +0.050] | False |
| 7 | 1.000 | +90.749 | +0.000 | +0.025 | [+0.000, +0.050] | False |
| 8 | 1.000 | +90.749 | +0.000 | +0.025 | [+0.000, +0.050] | False |

**Verdict: `search`** — by the pre-registered rule.
