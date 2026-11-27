# The value of a held free transfer on the component forecast

Protocol: [pre-registration](component_banked_transfer_value_prereg.md). Record: `component_banked_transfer_value.json`. Measurement only, no default moved.

## Reading

**move**, banked value 0.5.

- Levels passing the gate against 0 (primary): 0.5.
- Levels with the interval above zero and at most 1 losing season (primary): 0.5.
- Levels whose interval is below zero (primary): none.
- Highest pooled mean (primary): 0.5, inside the grid.
- Each season's own cap: **unsupported**; agrees with the primary: False.
- Form-window control (description): **unsupported**.
- Gate: mean paired gain of at least 1.5 points a gameweek, 90% interval above zero, lower season net in at most 1 season. 7 levels are compared with one baseline on one population; the intervals are not corrected for that.

## Component base, bank cap 5 in every season (primary)

| Banked value | Net a week | Mean season net | 2021-22 | 2022-23 | 2023-24 | 2024-25 | Free used | Paid | Lost at cap | Held a week | Proven |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 55.18 | 2028.0 | 2092 | 2065 | 1981 | 1974 | 147 | 1 | 0 | 1.03 | 1.000 |
| 0.5 | 57.78 | 2123.5 | 2092 | 2217 | 2070 | 2115 | 147 | 2 | 0 | 1.12 | 0.993 |
| 1 | 55.96 | 2056.5 | 1950 | 2120 | 2033 | 2123 | 147 | 0 | 0 | 1.61 | 0.973 |
| 1.5 | 55.07 | 2024.0 | 1972 | 2118 | 1871 | 2135 | 145 | 1 | 0 | 2.59 | 0.959 |
| 2 | 54.07 | 1987.2 | 1827 | 2152 | 2012 | 1958 | 142 | 0 | 0 | 3.11 | 0.966 |
| 3 | 54.91 | 2018.0 | 1861 | 2179 | 1977 | 2055 | 136 | 0 | 0 | 3.69 | 0.939 |
| 4 | 54.04 | 1986.0 | 1813 | 2178 | 1942 | 2011 | 133 | 0 | 0 | 4.31 | 0.939 |
| 6 | 54.05 | 1986.5 | 1853 | 2128 | 2083 | 1882 | 131 | 0 | 0 | 4.71 | 0.966 |

| Against 0 | Mean a week | 90% interval | Paired weeks | 2021-22 | 2022-23 | 2023-24 | 2024-25 |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 0.5 | +2.60 | [+1.21, +4.07] | 147 | +0 | +152 | +89 | +141 |
| 1 | +0.78 | [-0.96, +3.17] | 147 | -142 | +55 | +52 | +149 |
| 1.5 | -0.11 | [-1.94, +1.95] | 147 | -120 | +53 | -110 | +161 |
| 2 | -1.11 | [-2.82, +0.59] | 147 | -265 | +87 | +31 | -16 |
| 3 | -0.27 | [-1.90, +1.64] | 147 | -231 | +114 | -4 | +81 |
| 4 | -1.14 | [-3.02, +0.91] | 147 | -279 | +113 | -39 | +37 |
| 6 | -1.13 | [-2.13, +0.19] | 147 | -239 | +63 | +102 | -92 |

## Component base, each season's own bank cap

| Banked value | Net a week | Mean season net | 2021-22 | 2022-23 | 2023-24 | 2024-25 | Free used | Paid | Lost at cap | Held a week | Proven |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 55.18 | 2028.0 | 2092 | 2065 | 1981 | 1974 | 147 | 1 | 0 | 1.03 | 1.000 |
| 0.5 | 56.42 | 2073.5 | 2092 | 2017 | 2070 | 2115 | 147 | 1 | 0 | 1.08 | 0.993 |
| 1 | 55.78 | 2050.0 | 1950 | 2087 | 2040 | 2123 | 147 | 0 | 0 | 1.44 | 0.986 |
| 1.5 | 55.26 | 2030.8 | 1773 | 2226 | 1989 | 2135 | 144 | 1 | 0 | 1.80 | 0.980 |
| 2 | 53.63 | 1971.0 | 1896 | 2109 | 1921 | 1958 | 142 | 0 | 0 | 1.99 | 0.973 |
| 3 | 54.83 | 2015.0 | 1973 | 2110 | 1922 | 2055 | 140 | 1 | 0 | 2.39 | 0.986 |
| 4 | 53.90 | 1980.8 | 1909 | 2075 | 1928 | 2011 | 140 | 0 | 0 | 2.57 | 0.980 |
| 6 | 53.65 | 1971.8 | 1976 | 2054 | 1975 | 1882 | 140 | 0 | 0 | 2.65 | 1.000 |

| Against 0 | Mean a week | 90% interval | Paired weeks | 2021-22 | 2022-23 | 2023-24 | 2024-25 |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 0.5 | +1.24 | [-0.18, +2.71] | 147 | +0 | -48 | +89 | +141 |
| 1 | +0.60 | [-1.29, +2.70] | 147 | -142 | +22 | +59 | +149 |
| 1.5 | +0.07 | [-2.00, +2.12] | 147 | -319 | +161 | +8 | +161 |
| 2 | -1.55 | [-3.86, +0.47] | 147 | -196 | +44 | -60 | -16 |
| 3 | -0.35 | [-2.07, +1.29] | 147 | -119 | +45 | -59 | +81 |
| 4 | -1.29 | [-3.16, +0.65] | 147 | -183 | +10 | -53 | +37 |
| 6 | -1.53 | [-3.02, -0.26] | 147 | -116 | -11 | -6 | -92 |

## Form-window control, each season's own bank cap (description)

| Banked value | Net a week | Mean season net | 2021-22 | 2022-23 | 2023-24 | 2024-25 | Free used | Paid | Lost at cap | Held a week | Proven |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | 54.11 | 1988.5 | 2020 | 2077 | 1846 | 2011 | 147 | 36 | 0 | 1.03 | 0.993 |
| 0.5 | 54.11 | 1988.5 | 2020 | 2077 | 1846 | 2011 | 147 | 36 | 0 | 1.03 | 0.993 |
| 1 | 53.37 | 1961.5 | 2020 | 2036 | 1846 | 1944 | 147 | 30 | 0 | 1.03 | 0.993 |
| 1.5 | 53.86 | 1979.2 | 2020 | 2107 | 1846 | 1944 | 147 | 31 | 0 | 1.04 | 1.000 |
| 2 | 52.90 | 1944.0 | 1867 | 2107 | 1858 | 1944 | 147 | 35 | 0 | 1.07 | 0.993 |
| 3 | 52.27 | 1921.0 | 1885 | 2010 | 1858 | 1931 | 147 | 35 | 0 | 1.13 | 1.000 |
| 4 | 53.18 | 1954.5 | 1954 | 2034 | 1829 | 2001 | 146 | 34 | 0 | 1.46 | 1.000 |
| 6 | 53.22 | 1956.0 | 1997 | 2045 | 1859 | 1923 | 142 | 24 | 0 | 2.10 | 0.993 |

| Against 0 | Mean a week | 90% interval | Paired weeks | 2021-22 | 2022-23 | 2023-24 | 2024-25 |
| ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 0.5 | +0.00 | [+0.00, +0.00] | 147 | +0 | +0 | +0 | +0 |
| 1 | -0.73 | [-1.69, +0.07] | 147 | +0 | -41 | +0 | -67 |
| 1.5 | -0.25 | [-1.39, +0.71] | 147 | +0 | +30 | +0 | -67 |
| 2 | -1.21 | [-2.54, +0.04] | 147 | -153 | +30 | +12 | -67 |
| 3 | -1.84 | [-2.97, -0.56] | 147 | -135 | -67 | +12 | -80 |
| 4 | -0.93 | [-2.00, +0.09] | 147 | -66 | -43 | -17 | -10 |
| 6 | -0.88 | [-2.05, +0.50] | 147 | -23 | -32 | +13 | -88 |

## What was walked

- Seasons: 2021-22, 2022-23, 2023-24, 2024-25; one squad a season from its first decision gameweek to its last, lookahead 1, planning hit cost 8, the game's charge of 4 on the sheet, chips off, no transfer cap, sell-on fee halved, no automatic substitution.
- Free transfers lost at cap: weeks that start at the bank cap and make no transfer.
- Component handoff: table `b05f10c3fd3a`, 147 folds, model `phase_c_control_components_v1`; digests equal to the component record's: True.
- Solver: deterministic budget 8.0, 3469 of 3528 decisions proved.
- Code: `af32d5020ed8`, working tree dirty: False. Per-week rows: `artifacts/component_banked_transfer_value/weeks.json`.

[Research guide](README.md).
