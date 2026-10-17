# A mean-reversion discount for the later weeks of a multi-week plan

Protocol `docs/research/mean_reversion_discount_prereg.md`, commit `e112fede8371232022b2df8035203e5fabd83605`, archive commit `8c97b2adb123863c3dd581e730f1360e89815ac2`, run from 2026-10-17T11:38:12+00:00 to 2026-10-17T12:34:46+00:00. Seasons 2021-22, 2022-23, 2023-24, 2024-25, 2025-26 under development scope `v2`; 2025-26 is declared development data and never a test. Measurement only, nothing promoted.

## Verdict

**measured, not certified.** Primary comparison `L3_mr_0.75` minus `L3_naive`, realized points net of charged hits, paired per gameweek: mean -0.56 points per gameweek, 90% interval [-1.51, +0.89], noise floor 1.5 points per gameweek. Clears the floor: False. Interval excludes zero: False. Seasons where the candidate's net is below `L3_naive`: 2022-23, 2024-25 (at most 1 allowed).

## The deciding table

| Comparison | Paired weeks | Weekly mean | 90% interval | Weeks > 0 | Season nets |
| --- | ---: | ---: | --- | ---: | --- |
| `L3_mr_0.75` minus `L3_naive` (primary) | 184 | -0.56 | [-1.51, +0.89] | 0.29 | 2021-22 +63, 2022-23 -189, 2023-24 +18, 2024-25 -4, 2025-26 +9 |
| `L3_mr_0.9` minus `L3_naive` | 184 | -0.03 | [-0.83, +0.64] | 0.19 | 2021-22 +19, 2022-23 -3, 2023-24 +0, 2024-25 -49, 2025-26 +28 |
| `L3_mr_0.6` minus `L3_naive` | 184 | -0.14 | [-0.76, +0.90] | 0.31 | 2021-22 +34, 2022-23 -47, 2023-24 +9, 2024-25 -17, 2025-26 -5 |
| `L3_mr_0.75` minus `L1` | 184 | -1.07 | [-2.52, +0.26] | 0.29 | 2021-22 -60, 2022-23 -130, 2023-24 +58, 2024-25 -76, 2025-26 +11 |
| `L3_mr_0.9` minus `L1` | 184 | -0.54 | [-1.84, +0.07] | 0.30 | 2021-22 -104, 2022-23 +56, 2023-24 +40, 2024-25 -121, 2025-26 +30 |
| `L3_mr_0.6` minus `L1` | 184 | -0.65 | [-1.74, +0.31] | 0.29 | 2021-22 -89, 2022-23 +12, 2023-24 +49, 2024-25 -89, 2025-26 -3 |
| `L3_naive` minus `L1` | 184 | -0.51 | [-1.79, +0.34] | 0.33 | 2021-22 -123, 2022-23 +59, 2023-24 +40, 2024-25 -72, 2025-26 +2 |

## Season totals per arm (net of charged hits)

| Season | Arm | Decisions | Realized | Hits | Net | Transfers | Paid | Reversals | Carried blank | Carried holes | Proven | Mean gap | Seconds per decision |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 2021-22 | `L1` | 37 | 2084 | 64 | 2020 | 53 | 16 | 10 | 36 | 0 | 1.00 | 0.000 | 7.0 |
| 2021-22 | `L3_naive` | 37 | 1897 | 0 | 1897 | 37 | 0 | 2 | 44 | 0 | 0.35 | 0.190 | 33.4 |
| 2021-22 | `L3_mr_0.75` | 37 | 1960 | 0 | 1960 | 37 | 0 | 4 | 42 | 0 | 0.46 | 0.148 | 22.7 |
| 2021-22 | `L3_mr_0.9` | 37 | 1916 | 0 | 1916 | 37 | 0 | 6 | 42 | 0 | 0.35 | 0.172 | 16.6 |
| 2021-22 | `L3_mr_0.6` | 37 | 1931 | 0 | 1931 | 37 | 0 | 4 | 41 | 0 | 0.62 | 0.097 | 11.7 |
| 2022-23 | `L1` | 36 | 2101 | 40 | 2061 | 46 | 10 | 5 | 30 | 0 | 1.00 | 0.000 | 5.9 |
| 2022-23 | `L3_naive` | 36 | 2120 | 0 | 2120 | 36 | 0 | 2 | 26 | 0 | 0.75 | 0.055 | 28.2 |
| 2022-23 | `L3_mr_0.75` | 36 | 1931 | 0 | 1931 | 36 | 0 | 2 | 26 | 0 | 0.81 | 0.049 | 23.9 |
| 2022-23 | `L3_mr_0.9` | 36 | 2117 | 0 | 2117 | 36 | 0 | 2 | 26 | 0 | 0.81 | 0.048 | 13.2 |
| 2022-23 | `L3_mr_0.6` | 36 | 2073 | 0 | 2073 | 36 | 0 | 2 | 25 | 0 | 0.81 | 0.045 | 11.7 |
| 2023-24 | `L1` | 37 | 1870 | 24 | 1846 | 43 | 6 | 4 | 20 | 0 | 1.00 | 0.000 | 5.4 |
| 2023-24 | `L3_naive` | 37 | 1886 | 0 | 1886 | 37 | 0 | 0 | 18 | 0 | 0.84 | 0.042 | 25.7 |
| 2023-24 | `L3_mr_0.75` | 37 | 1904 | 0 | 1904 | 37 | 0 | 1 | 18 | 0 | 0.92 | 0.027 | 23.1 |
| 2023-24 | `L3_mr_0.9` | 37 | 1886 | 0 | 1886 | 37 | 0 | 0 | 19 | 0 | 0.84 | 0.046 | 13.1 |
| 2023-24 | `L3_mr_0.6` | 37 | 1895 | 0 | 1895 | 37 | 0 | 1 | 18 | 0 | 0.92 | 0.025 | 11.0 |
| 2024-25 | `L1` | 37 | 2023 | 12 | 2011 | 40 | 3 | 4 | 17 | 0 | 1.00 | 0.000 | 4.6 |
| 2024-25 | `L3_naive` | 37 | 1939 | 0 | 1939 | 37 | 0 | 2 | 12 | 0 | 0.49 | 0.094 | 34.9 |
| 2024-25 | `L3_mr_0.75` | 37 | 1935 | 0 | 1935 | 37 | 0 | 3 | 9 | 0 | 0.68 | 0.052 | 22.2 |
| 2024-25 | `L3_mr_0.9` | 37 | 1890 | 0 | 1890 | 37 | 0 | 6 | 10 | 0 | 0.54 | 0.098 | 15.1 |
| 2024-25 | `L3_mr_0.6` | 37 | 1922 | 0 | 1922 | 37 | 0 | 3 | 9 | 0 | 0.84 | 0.027 | 11.9 |
| 2025-26 | `L1` | 37 | 1806 | 4 | 1802 | 38 | 1 | 2 | 13 | 0 | 1.00 | 0.000 | 6.5 |
| 2025-26 | `L3_naive` | 37 | 1804 | 0 | 1804 | 37 | 0 | 2 | 10 | 0 | 0.70 | 0.068 | 29.8 |
| 2025-26 | `L3_mr_0.75` | 37 | 1813 | 0 | 1813 | 37 | 0 | 1 | 10 | 0 | 0.81 | 0.038 | 22.4 |
| 2025-26 | `L3_mr_0.9` | 37 | 1832 | 0 | 1832 | 37 | 0 | 2 | 10 | 0 | 0.70 | 0.066 | 14.5 |
| 2025-26 | `L3_mr_0.6` | 37 | 1799 | 0 | 1799 | 37 | 0 | 1 | 10 | 0 | 0.86 | 0.029 | 11.6 |

## Decomposition (candidate minus baseline)

Selection is realized points before hits; hits are the charged hit points. Weekly means are over the paired gameweeks; season figures are season totals.

| Comparison | Weekly selection | Weekly hits | Season selection | Season hits |
| --- | ---: | ---: | --- | --- |
| `L3_mr_0.75` minus `L3_naive` | -0.56 | +0.00 | 2021-22 +63, 2022-23 -189, 2023-24 +18, 2024-25 -4, 2025-26 +9 | 2021-22 +0, 2022-23 +0, 2023-24 +0, 2024-25 +0, 2025-26 +0 |
| `L3_mr_0.9` minus `L3_naive` | -0.03 | +0.00 | 2021-22 +19, 2022-23 -3, 2023-24 +0, 2024-25 -49, 2025-26 +28 | 2021-22 +0, 2022-23 +0, 2023-24 +0, 2024-25 +0, 2025-26 +0 |
| `L3_mr_0.6` minus `L3_naive` | -0.14 | +0.00 | 2021-22 +34, 2022-23 -47, 2023-24 +9, 2024-25 -17, 2025-26 -5 | 2021-22 +0, 2022-23 +0, 2023-24 +0, 2024-25 +0, 2025-26 +0 |
| `L3_mr_0.75` minus `L1` | -1.85 | -0.78 | 2021-22 -124, 2022-23 -170, 2023-24 +34, 2024-25 -88, 2025-26 +7 | 2021-22 -64, 2022-23 -40, 2023-24 -24, 2024-25 -12, 2025-26 -4 |
| `L3_mr_0.9` minus `L1` | -1.32 | -0.78 | 2021-22 -168, 2022-23 +16, 2023-24 +16, 2024-25 -133, 2025-26 +26 | 2021-22 -64, 2022-23 -40, 2023-24 -24, 2024-25 -12, 2025-26 -4 |
| `L3_mr_0.6` minus `L1` | -1.43 | -0.78 | 2021-22 -153, 2022-23 -28, 2023-24 +25, 2024-25 -101, 2025-26 -7 | 2021-22 -64, 2022-23 -40, 2023-24 -24, 2024-25 -12, 2025-26 -4 |
| `L3_naive` minus `L1` | -1.29 | -0.78 | 2021-22 -187, 2022-23 +19, 2023-24 +16, 2024-25 -84, 2025-26 -2 | 2021-22 -64, 2022-23 -40, 2023-24 -24, 2024-25 -12, 2025-26 -4 |

## Solver and statistics

- Deterministic budget 8.0 per solve, wall clock cap 60.0 s; 702 of 920 decisions proved optimal; OR-Tools 9.15.6755.
- Intervals: 90% season-aware moving-block bootstrap, blocks of 4 consecutive weeks, 2000 resamples, seed 0, on per-gameweek paired differences.
- Noise floor: an effect below 1.5 points per gameweek is not certified.
- Reversals: a purchased player sold within 3 gameweeks of purchase.
- Carried rows: squad members the chain carried at a zero projection because their club was blank that week (blank) or the archive had no row for them (holes). Under the mean-reversion rule such a member projects the position mean times one minus rho to the offset in a later week, where the naive rule keeps them at zero; the counts above size that side effect per chain.

## Provenance

- Repository commit `e112fede8371232022b2df8035203e5fabd83605`, working tree dirty: False; archive commit `8c97b2adb123863c3dd581e730f1360e89815ac2`.
- The chains ran at `e112fede8371232022b2df8035203e5fabd83605`; this record was merged at `537520b72e989be2965da8f938a4b9a91501064b` (working tree dirty at the merge: False) from the per-season artifacts below, whose sha256 digests name the chain output the merge read. Where the two commits differ, the code that changed between them changed what the merge keeps of each chain and nothing in the chain, so the numbers stand (protocol step 4).
- Per-week expansion `artifacts/mean_reversion_discount/weeks.json` (gitignored), sha256 `2e5cd417254029fc804cafc3d07d121e545a83294559070f443b5777fee0d63c`.
- Machine: Linux-6.18.44-fc-v139-x86_64-with-glibc2.39, 4 logical cores, Python 3.13.16; one process per season in parallel.
- Merged from: `artifacts/mean_reversion_discount/2021-22.json` sha256 `c57c8440b1ef266ae72dd9092b19cf9bb5e35fc76bfab7d1db921f353d75b51b`; `artifacts/mean_reversion_discount/2022-23.json` sha256 `d54661da3551486ca2691ad6a7c46afbbc41654924f41a35e1bbeac53a4ed357`; `artifacts/mean_reversion_discount/2023-24.json` sha256 `a158f7cf070758a005cad94d46382462f3c3d734ce53e5258055a14558016e07`; `artifacts/mean_reversion_discount/2024-25.json` sha256 `d948f3b1959c09bd6f49ebfdf2e5ee2521f8ee1080ab89638697c181ae4da8e7`; `artifacts/mean_reversion_discount/2025-26.json` sha256 `b447f3c8956cdcbdaa936390dc7125bf3b52f7f08e88019cd789edbe10e5039f`.
