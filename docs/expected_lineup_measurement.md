# Bench40 complete matrix

All 42 final records and all 14 matched settings are included.

Code provenance: base HEAD `b42b6ab136bda55f66157184e3c0c063addfd148` with uncommitted expected-lineup changes in a frozen working tree. This was not a clean-commit benchmark. The JSON names unchanged measured core file hashes, which are not a complete archive of that tree. The later LLM/minute integration and one-proposal diagnostic correction were tested separately; they were not part of these 42 runs.

## Nominal expected net points

| Weeks | Top100 | Expected | Legacy | Zero | Delta vs legacy | Delta vs zero |
| --- | --- | --- | --- | --- | --- | --- |
| 3 | 0 | 154.930 | 154.440 | 154.405 | +0.490 | +0.525 |
| 3 | 5 | 154.966 | 154.476 | 154.405 | +0.490 | +0.560 |
| 3 | 10 | 154.690 | 154.204 | 154.668 | +0.486 | +0.021 |
| 3 | 20 | 154.544 | 154.063 | 154.063 | +0.482 | +0.482 |
| 3 | 30 | 154.427 | 154.063 | 152.663 | +0.365 | +1.764 |
| 3 | 40 | 154.427 | 151.847 | 151.847 | +2.580 | +2.580 |
| 3 | 50 | 151.409 | 151.473 | 151.473 | -0.063 | -0.063 |
| 5 | 0 | 260.106 | 259.091 | 260.556 | +1.015 | -0.449 |
| 5 | 5 | 260.081 | 252.568 | 260.117 | +7.514 | -0.036 |
| 5 | 10 | 256.291 | 256.233 | 257.715 | +0.057 | -1.425 |
| 5 | 20 | 255.057 | 255.065 | 257.125 | -0.007 | -2.068 |
| 5 | 30 | 259.805 | 253.983 | 258.063 | +5.822 | +1.742 |
| 5 | 40 | 256.285 | 255.915 | 258.822 | +0.370 | -2.538 |
| 5 | 50 | 254.202 | 254.229 | 254.556 | -0.027 | -0.354 |

## Conditional expected net points

| Weeks | Top100 | Expected | Legacy | Zero | Delta vs legacy | Delta vs zero |
| --- | --- | --- | --- | --- | --- | --- |
| 3 | 0 | 155.003 | 154.930 | 154.930 | +0.073 | +0.073 |
| 3 | 5 | 154.966 | 154.966 | 154.930 | +0.000 | +0.035 |
| 3 | 10 | 154.690 | 154.693 | 154.658 | -0.003 | +0.032 |
| 3 | 20 | 154.544 | 154.552 | 154.580 | -0.008 | -0.036 |
| 3 | 30 | 154.427 | 154.552 | 152.663 | -0.125 | +1.764 |
| 3 | 40 | 154.427 | 151.847 | 151.847 | +2.580 | +2.580 |
| 3 | 50 | 151.409 | 151.473 | 151.473 | -0.063 | -0.063 |
| 5 | 0 | 259.924 | 259.521 | 259.955 | +0.403 | -0.030 |
| 5 | 5 | 257.208 | 252.556 | 260.117 | +4.652 | -2.910 |
| 5 | 10 | 256.291 | 256.261 | 257.713 | +0.030 | -1.423 |
| 5 | 20 | 254.916 | 255.065 | 257.173 | -0.149 | -2.257 |
| 5 | 30 | 258.533 | 254.459 | 255.642 | +4.074 | +2.891 |
| 5 | 40 | 256.285 | 255.915 | 258.822 | +0.370 | -2.538 |
| 5 | 50 | 254.202 | 254.229 | 254.556 | -0.027 | -0.354 |

## Common Top100 nominal selection utility (preference units, not FPL points)

| Weeks | Top100 | Expected | Legacy | Zero | Delta vs legacy | Delta vs zero |
| --- | --- | --- | --- | --- | --- | --- |
| 3 | 0 | 154.930 | 154.440 | 154.405 | +0.490 | +0.525 |
| 3 | 5 | 157.855 | 157.359 | 157.216 | +0.495 | +0.638 |
| 3 | 10 | 160.817 | 160.316 | 160.689 | +0.502 | +0.128 |
| 3 | 20 | 166.952 | 166.434 | 166.434 | +0.518 | +0.518 |
| 3 | 30 | 173.167 | 172.619 | 171.538 | +0.548 | +1.629 |
| 3 | 40 | 179.414 | 178.064 | 178.064 | +1.350 | +1.350 |
| 3 | 50 | 184.816 | 184.695 | 184.695 | +0.121 | +0.121 |
| 5 | 0 | 260.106 | 259.091 | 260.556 | +1.015 | -0.449 |
| 5 | 5 | 264.595 | 257.251 | 264.987 | +7.344 | -0.392 |
| 5 | 10 | 266.125 | 266.049 | 267.285 | +0.076 | -1.160 |
| 5 | 20 | 275.142 | 275.121 | 276.712 | +0.021 | -1.570 |
| 5 | 30 | 289.752 | 283.245 | 288.940 | +6.507 | +0.812 |
| 5 | 40 | 299.215 | 298.388 | 301.924 | +0.827 | -2.709 |
| 5 | 50 | 310.908 | 310.876 | 308.241 | +0.032 | +2.667 |

## Common Top100 conditional selection utility (preference units, not FPL points)

| Weeks | Top100 | Expected | Legacy | Zero | Delta vs legacy | Delta vs zero |
| --- | --- | --- | --- | --- | --- | --- |
| 3 | 0 | 155.003 | 154.930 | 154.930 | +0.073 | +0.073 |
| 3 | 5 | 157.855 | 157.855 | 157.768 | +0.000 | +0.086 |
| 3 | 10 | 160.817 | 160.817 | 160.679 | +0.000 | +0.138 |
| 3 | 20 | 166.952 | 166.946 | 166.850 | +0.005 | +0.102 |
| 3 | 30 | 173.167 | 173.143 | 171.538 | +0.024 | +1.629 |
| 3 | 40 | 179.414 | 178.064 | 178.064 | +1.350 | +1.350 |
| 3 | 50 | 184.816 | 184.695 | 184.695 | +0.121 | +0.121 |
| 5 | 0 | 259.924 | 259.521 | 259.955 | +0.403 | -0.030 |
| 5 | 5 | 261.757 | 257.239 | 264.987 | +4.518 | -3.230 |
| 5 | 10 | 266.125 | 266.099 | 267.367 | +0.025 | -1.242 |
| 5 | 20 | 275.157 | 275.121 | 276.995 | +0.036 | -1.838 |
| 5 | 30 | 289.694 | 285.990 | 286.991 | +3.704 | +2.704 |
| 5 | 40 | 299.215 | 298.388 | 301.924 | +0.827 | -2.709 |
| 5 | 50 | 310.908 | 310.876 | 308.241 | +0.032 | +2.667 |

## Descriptive sign counts

| Weeks | Comparison | Positive | Negative | Tie | Missing |
| --- | --- | --- | --- | --- | --- |
| all | raw_nominal_expected_net_vs_legacy | 11 | 3 | 0 | 0 |
| all | raw_nominal_expected_net_vs_zero | 7 | 7 | 0 | 0 |
| all | raw_conditional_expected_net_vs_legacy | 7 | 6 | 1 | 0 |
| all | raw_conditional_expected_net_vs_zero | 6 | 8 | 0 | 0 |
| all | common_top100_nominal_selection_utility_vs_legacy | 14 | 0 | 0 | 0 |
| all | common_top100_nominal_selection_utility_vs_zero | 9 | 5 | 0 | 0 |
| all | common_top100_conditional_selection_utility_vs_legacy | 13 | 0 | 1 | 0 |
| all | common_top100_conditional_selection_utility_vs_zero | 9 | 5 | 0 | 0 |
| 3 | raw_nominal_expected_net_vs_legacy | 6 | 1 | 0 | 0 |
| 3 | raw_nominal_expected_net_vs_zero | 6 | 1 | 0 | 0 |
| 3 | raw_conditional_expected_net_vs_legacy | 2 | 4 | 1 | 0 |
| 3 | raw_conditional_expected_net_vs_zero | 5 | 2 | 0 | 0 |
| 3 | common_top100_nominal_selection_utility_vs_legacy | 7 | 0 | 0 | 0 |
| 3 | common_top100_nominal_selection_utility_vs_zero | 7 | 0 | 0 | 0 |
| 3 | common_top100_conditional_selection_utility_vs_legacy | 6 | 0 | 1 | 0 |
| 3 | common_top100_conditional_selection_utility_vs_zero | 7 | 0 | 0 | 0 |
| 5 | raw_nominal_expected_net_vs_legacy | 5 | 2 | 0 | 0 |
| 5 | raw_nominal_expected_net_vs_zero | 1 | 6 | 0 | 0 |
| 5 | raw_conditional_expected_net_vs_legacy | 5 | 2 | 0 | 0 |
| 5 | raw_conditional_expected_net_vs_zero | 1 | 6 | 0 | 0 |
| 5 | common_top100_nominal_selection_utility_vs_legacy | 7 | 0 | 0 | 0 |
| 5 | common_top100_nominal_selection_utility_vs_zero | 2 | 5 | 0 | 0 |
| 5 | common_top100_conditional_selection_utility_vs_legacy | 7 | 0 | 0 | 0 |
| 5 | common_top100_conditional_selection_utility_vs_zero | 2 | 5 | 0 | 0 |

## Work and latency for every case

| Weeks/Top100 | Variant | Status/candidates | CP actual/allocated/configured | Role evals | Known search states | Fixed evals with unknown states | Publication evals/states | Seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 3/0 | expected | compared/2 | 47.738/54.000/60.000 | 3223 | 1711560 | 15 | 0/0 | 68.049 |
| 3/0 | legacy | compared/2 | 47.719/54.000/60.000 | 0 | 0 | 0 | 0/0 | 60.522 |
| 3/0 | zero | compared/2 | 49.195/54.000/60.000 | 0 | 0 | 0 | 0/0 | 65.091 |
| 3/5 | expected | compared/2 | 50.454/54.000/60.000 | 3223 | 1711160 | 15 | 3/1536 | 79.050 |
| 3/5 | legacy | compared/2 | 50.504/54.000/60.000 | 0 | 0 | 0 | 0/0 | 54.669 |
| 3/5 | zero | compared/2 | 50.515/54.000/60.000 | 0 | 0 | 0 | 0/0 | 58.625 |
| 3/10 | expected | compared/2 | 47.493/54.000/60.000 | 3223 | 1709928 | 15 | 3/1536 | 64.327 |
| 3/10 | legacy | compared/2 | 47.572/54.000/60.000 | 0 | 0 | 0 | 0/0 | 58.104 |
| 3/10 | zero | compared/2 | 48.870/54.000/60.000 | 0 | 0 | 0 | 0/0 | 56.983 |
| 3/20 | expected | compared/2 | 50.492/54.000/60.000 | 3223 | 1745320 | 15 | 3/1656 | 70.836 |
| 3/20 | legacy | compared/2 | 50.569/54.000/60.000 | 0 | 0 | 0 | 0/0 | 59.035 |
| 3/20 | zero | compared/2 | 49.279/54.000/60.000 | 0 | 0 | 0 | 0/0 | 58.749 |
| 3/30 | expected | compared/2 | 47.854/54.000/60.000 | 3223 | 1783768 | 15 | 3/1656 | 63.666 |
| 3/30 | legacy | compared/2 | 47.890/54.000/60.000 | 0 | 0 | 0 | 0/0 | 54.576 |
| 3/30 | zero | compared/2 | 50.688/54.000/60.000 | 0 | 0 | 0 | 0/0 | 58.506 |
| 3/40 | expected | compared/3 | 52.820/60.000/60.000 | 4774 | 2733872 | 24 | 3/1656 | 76.991 |
| 3/40 | legacy | compared/2 | 46.911/54.000/60.000 | 0 | 0 | 0 | 0/0 | 55.181 |
| 3/40 | zero | compared/3 | 46.631/54.000/60.000 | 0 | 0 | 0 | 0/0 | 54.726 |
| 3/50 | expected | compared/2 | 48.052/54.000/60.000 | 3223 | 1878304 | 15 | 3/1776 | 66.652 |
| 3/50 | legacy | compared/2 | 48.047/54.000/60.000 | 0 | 0 | 0 | 0/0 | 55.930 |
| 3/50 | zero | compared/2 | 46.345/54.000/60.000 | 0 | 0 | 0 | 0/0 | 55.863 |
| 5/0 | expected | compared/3 | 94.976/100.000/100.000 | 9142 | 5121048 | 40 | 0/0 | 160.759 |
| 5/0 | legacy | compared/2 | 84.839/90.000/100.000 | 0 | 0 | 0 | 0/0 | 116.306 |
| 5/0 | zero | compared/3 | 94.984/100.000/100.000 | 0 | 0 | 0 | 0/0 | 132.101 |
| 5/5 | expected | compared/3 | 95.005/100.000/100.000 | 9142 | 4603952 | 40 | 5/2784 | 169.703 |
| 5/5 | legacy | compared/3 | 85.006/90.000/100.000 | 0 | 0 | 0 | 0/0 | 124.379 |
| 5/5 | zero | compared/3 | 84.972/90.000/100.000 | 0 | 0 | 0 | 0/0 | 122.773 |
| 5/10 | expected | compared/3 | 84.976/90.000/100.000 | 8111 | 4620000 | 35 | 5/2712 | 158.963 |
| 5/10 | legacy | compared/2 | 84.864/90.000/100.000 | 0 | 0 | 0 | 0/0 | 115.341 |
| 5/10 | zero | compared/2 | 84.864/90.000/100.000 | 0 | 0 | 0 | 0/0 | 118.349 |
| 5/20 | expected | compared/2 | 84.837/90.000/100.000 | 6049 | 3510640 | 25 | 5/2896 | 139.326 |
| 5/20 | legacy | compared/3 | 84.992/90.000/100.000 | 0 | 0 | 0 | 0/0 | 118.576 |
| 5/20 | zero | compared/2 | 85.231/90.000/100.000 | 0 | 0 | 0 | 0/0 | 123.031 |
| 5/30 | expected | compared/3 | 94.975/100.000/100.000 | 9142 | 4573568 | 40 | 5/2808 | 168.321 |
| 5/30 | legacy | compared/2 | 84.835/90.000/100.000 | 0 | 0 | 0 | 0/0 | 125.256 |
| 5/30 | zero | compared/3 | 95.106/100.000/100.000 | 0 | 0 | 0 | 0/0 | 144.458 |
| 5/40 | expected | compared/2 | 84.888/90.000/100.000 | 6049 | 3485920 | 25 | 5/2808 | 137.511 |
| 5/40 | legacy | compared/3 | 85.030/90.000/100.000 | 0 | 0 | 0 | 0/0 | 111.062 |
| 5/40 | zero | compared/3 | 94.985/100.000/100.000 | 0 | 0 | 0 | 0/0 | 144.216 |
| 5/50 | expected | compared/3 | 84.975/90.000/100.000 | 8111 | 4699888 | 35 | 5/3032 | 138.947 |
| 5/50 | legacy | compared/2 | 84.837/90.000/100.000 | 0 | 0 | 0 | 0/0 | 110.755 |
| 5/50 | zero | compared/2 | 84.838/90.000/100.000 | 0 | 0 | 0 | 0/0 | 137.376 |

## Interpretation limits

- Scores are model expectations on the same unweighted football forecast scale, net of actual four-point paid transfers; they are not realized FPL gains.
- Conditional scores use the declared two-outcome information assumption; a missing complete comparison remains null.
- Top100 and the eight-point selection penalty influence choice; selection utility is not reported as an FPL points gain.
- The separate common Top100 tables rescore every variant on the same expected lineup basis and declared selection policy: the stored weighted net already charges four points per paid transfer, then another four-point premium is subtracted. There is no discount or terminal value. These units are preference utility, not actual FPL points; legacy bench-surrogate utility is not compared.
- Counts describe fourteen overlapping settings, not independent samples or evidence of calibrated improvement.
- Latency covers the dispatcher only, excluding input loading and posthoc common scoring.
- Recorded role-search states omit uninstrumented fixed-policy rescoring states; these unknown states are not presented as zero.
- No cited news artifact or external calibration is available for this capture. The news variant is identical without new evidence and is not solved again.
- This summary validates record structure and pairing; it does not replace independent resource and score replay.
