# P(ahead of the crowd) over a window

- Contract `windowed_rank_v1`; 2024-25, origins [8, 14, 20, 26, 32], horizons [1, 3, 5], 100 paths per window.
- The rival is the ownership template at the origin; the squad is chosen by the rank objective on the window's joint path totals via `as_window_scenario_set`: the same solver that prices a single week, unchanged.
- Each window week repeats the origin's projection; the control produces one week and the calendar-aware GW2+ projection is the data side's deliverable.
- Rival edge: **+7.19 points per week** added to the rival's scenario scores (zero = the crowd priced at the projection, the historical behaviour).
- Solves: {'FEASIBLE': 14, 'OPTIMAL': 1}. Each stops on deterministic solver work (the rank objective's own budget), so the same commit writes the same record on a busy machine; an incumbent is still an incumbent and is labelled as one.
- Descriptive measurement: no gate, nothing promoted; seasons loaded ['2020-21', '2021-22', '2022-23', '2023-24', '2024-25'], the locked holdout is not among them.

| Horizon | Windows | Mean claimed P(ahead) | Realized ahead share | Shared starters |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 5 | 0.77 | 0.60 | 3.6 |
| 3 | 5 | 0.87 | 0.00 | 3.6 |
| 5 | 5 | 0.89 | 0.00 | 3.8 |

Per window:

| Origin | Horizon | Claimed | Realized | Mine | Crowd |
| ---: | ---: | ---: | --- | ---: | ---: |
| 8 | 1 | 0.58 | ahead | 44 | 31 |
| 8 | 3 | 0.62 | behind | 108 | 129 |
| 8 | 5 | 0.56 | behind | 176 | 246 |
| 14 | 1 | 0.82 | behind | 55 | 67 |
| 14 | 3 | 0.91 | behind | 135 | 180 |
| 14 | 5 | 0.98 | behind | 260 | 289 |
| 20 | 1 | 0.81 | ahead | 83 | 79 |
| 20 | 3 | 0.94 | behind | 160 | 187 |
| 20 | 5 | 0.99 | behind | 352 | 380 |
| 26 | 1 | 0.81 | behind | 60 | 74 |
| 26 | 3 | 0.92 | behind | 189 | 196 |
| 26 | 5 | 0.96 | behind | 208 | 257 |
| 32 | 1 | 0.82 | ahead | 59 | 51 |
| 32 | 3 | 0.97 | behind | 119 | 156 |
| 32 | 5 | 0.98 | behind | 193 | 249 |

