# P(ahead of the crowd) over a window

- Contract `windowed_rank_v1`; 2024-25, origins [8, 14, 20, 26, 32], horizons [1, 3, 5], 100 paths per window.
- The rival is the ownership template at the origin; the squad is chosen by the rank objective on the window's joint path totals via `as_window_scenario_set` — the same solver that prices a single week, unchanged.
- Each window week repeats the origin's projection; the control produces one week and the calendar-aware GW2+ projection is the data side's deliverable.
- Descriptive measurement: no gate, nothing promoted, locked holdout untouched.

| Horizon | Windows | Mean claimed P(ahead) | Realized ahead share | Shared starters |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 5 | 0.89 | 0.60 | 4.0 |
| 3 | 5 | 0.97 | 0.00 | 3.6 |
| 5 | 5 | 0.99 | 0.00 | 3.6 |

Per window:

| Origin | Horizon | Claimed | Realized | Mine | Crowd |
| ---: | ---: | ---: | --- | ---: | ---: |
| 8 | 1 | 0.74 | ahead | 44 | 31 |
| 8 | 3 | 0.87 | behind | 108 | 129 |
| 8 | 5 | 0.96 | behind | 176 | 246 |
| 14 | 1 | 0.89 | behind | 55 | 67 |
| 14 | 3 | 0.99 | behind | 135 | 180 |
| 14 | 5 | 1.00 | behind | 260 | 289 |
| 20 | 1 | 0.92 | ahead | 83 | 79 |
| 20 | 3 | 0.99 | behind | 160 | 187 |
| 20 | 5 | 1.00 | behind | 329 | 380 |
| 26 | 1 | 0.93 | behind | 67 | 74 |
| 26 | 3 | 1.00 | behind | 189 | 196 |
| 26 | 5 | 1.00 | behind | 208 | 257 |
| 32 | 1 | 0.95 | ahead | 67 | 51 |
| 32 | 3 | 1.00 | behind | 106 | 156 |
| 32 | 5 | 1.00 | behind | 193 | 249 |

