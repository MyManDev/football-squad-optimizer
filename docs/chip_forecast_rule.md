# The chip forecast's rule under two sets of chips

Protocol: `docs/chip_forecast_prereg.md`. Lookahead-1 chains over 2021-22, 2022-23, 2023-24, 2024-25, this season's two chip windows laid over each.

| Season | Arm | Net | Hits | Chips played | Expired unplayed |
| --- | --- | ---: | ---: | --- | --- |
| 2021-22 | `off` | 1994 | 216 | none | n/a, no chip was offered |
| 2021-22 | `planner` | 2002 | 200 | GW2 bboost, GW20 wildcard, GW21 bboost, GW22 freehit, GW23 3xc, GW3 3xc, GW4 wildcard, GW5 freehit | none |
| 2021-22 | `fixed` | 2001 | 200 | GW17 freehit, GW2 3xc, GW20 wildcard, GW22 freehit, GW28 bboost, GW36 3xc, GW5 wildcard | bboost:1-19 |
| 2021-22 | `decaying` | 2051 | 196 | GW13 freehit, GW19 bboost, GW2 3xc, GW20 wildcard, GW22 freehit, GW26 bboost, GW27 3xc, GW5 wildcard | none |
| 2021-22 | `threshold_only` | 2056 | 196 | GW2 bboost, GW20 wildcard, GW22 freehit, GW23 bboost, GW26 3xc, GW5 wildcard, GW8 freehit, GW9 3xc | none |
| 2022-23 | `off` | 2013 | 188 | none | n/a, no chip was offered |
| 2022-23 | `planner` | 2060 | 160 | GW2 bboost, GW20 3xc, GW21 bboost, GW22 wildcard, GW23 freehit, GW3 wildcard, GW4 3xc, GW5 freehit | none |
| 2022-23 | `fixed` | 2110 | 112 | GW12 freehit, GW20 wildcard, GW22 3xc, GW25 freehit, GW29 bboost, GW3 wildcard | bboost:1-19, 3xc:1-19 |
| 2022-23 | `decaying` | 2139 | 128 | GW19 bboost, GW20 wildcard, GW22 3xc, GW23 bboost, GW25 freehit, GW3 wildcard, GW8 freehit, GW9 3xc | none |
| 2022-23 | `threshold_only` | 2139 | 124 | GW2 bboost, GW20 wildcard, GW22 3xc, GW23 bboost, GW25 freehit, GW3 wildcard, GW8 freehit, GW9 3xc | none |
| 2023-24 | `off` | 1724 | 144 | none | n/a, no chip was offered |
| 2023-24 | `planner` | 1832 | 116 | GW2 bboost, GW20 bboost, GW21 3xc, GW22 wildcard, GW23 freehit, GW3 3xc, GW4 freehit, GW5 wildcard | none |
| 2023-24 | `fixed` | 1952 | 84 | GW23 wildcard, GW25 freehit, GW35 3xc, GW37 bboost, GW9 wildcard | freehit:2-19, bboost:1-19, 3xc:1-19 |
| 2023-24 | `decaying` | 1804 | 108 | GW10 3xc, GW17 freehit, GW19 bboost, GW23 wildcard, GW25 freehit, GW27 3xc, GW28 bboost, GW7 wildcard | none |
| 2023-24 | `threshold_only` | 1837 | 96 | GW10 3xc, GW2 bboost, GW20 wildcard, GW25 freehit, GW27 3xc, GW28 bboost, GW7 wildcard, GW9 freehit | none |
| 2024-25 | `off` | 1919 | 124 | none | n/a, no chip was offered |
| 2024-25 | `planner` | 2074 | 92 | GW2 bboost, GW20 3xc, GW21 bboost, GW22 freehit, GW23 wildcard, GW3 3xc, GW4 wildcard, GW5 freehit | none |
| 2024-25 | `fixed` | 2033 | 72 | GW25 3xc, GW29 wildcard, GW32 freehit, GW7 wildcard | freehit:2-19, bboost:1-19, bboost:20-38, 3xc:1-19 |
| 2024-25 | `decaying` | 2037 | 68 | GW10 3xc, GW15 freehit, GW19 bboost, GW24 bboost, GW25 3xc, GW26 wildcard, GW29 freehit, GW7 wildcard | none |
| 2024-25 | `threshold_only` | 2021 | 84 | GW10 3xc, GW11 freehit, GW2 bboost, GW24 wildcard, GW25 3xc, GW27 bboost, GW28 freehit, GW7 wildcard | none |

Weeks that returned an incumbent rather than a proof, by the widest gap of the chain that holds them. The mean gap each chain records counts every proved week as a zero, so it is not the number to read here:

| Season | Arm | Widest weekly gap | Mean over all weeks |
| --- | --- | ---: | ---: |
| 2021-22 | `planner` | 0.2775 | 0.0075 |
| 2021-22 | `fixed` | 0.2916 | 0.0079 |
| 2021-22 | `threshold_only` | 0.2116 | 0.0057 |
| 2022-23 | `off` | 0.2729 | 0.0076 |
| 2024-25 | `planner` | 0.4680 | 0.0126 |
| 2024-25 | `threshold_only` | 0.3345 | 0.0090 |

| Comparison | Mean per season | Mean per gameweek | 90% interval, per gameweek | Seasons ahead |
| --- | ---: | ---: | --- | ---: |
| `decaying` minus `fixed` | -16.2 | -0.44 | [-1.35, +0.99] | 0.75 |
| `decaying` minus `threshold_only` | -5.5 | -0.15 | [-0.80, +1.01] | 0.25 |
| `threshold_only` minus `fixed` | -10.8 | -0.29 | [-1.59, +1.15] | 0.50 |
| `fixed` minus `off` | +111.5 | +3.03 | [+1.48, +4.50] | 1.00 |
| `decaying` minus `off` | +95.2 | +2.59 | [+1.22, +4.53] | 1.00 |
| `threshold_only` minus `off` | +100.8 | +2.74 | [+1.18, +4.26] | 1.00 |
| `planner` minus `off` | +79.5 | +2.16 | [+0.83, +3.24] | 1.00 |
