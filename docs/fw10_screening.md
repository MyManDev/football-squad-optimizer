# Sprint 2 screening DoE

Screening fingerprint: `d07f292f799a0e44acd725fd9260c2184e29fbd2ef3030a656f986b3e3cb9388`
Development seasons: `2021-22, 2022-23, 2023-24, 2024-25`
The locked holdout was not accessed by this run.

## Candidate responses

| Candidate | Mean realized | Paired delta | 90% CI | Feasibility | Eligible |
| --- | ---: | ---: | --- | ---: | --- |
| `fw03-bw0` | 51.218 | -2.558 | [-4.463, -0.980] | 1.000 | false |
| `fw03-bw0p1` | 50.986 | -2.789 | [-4.782, -1.095] | 1.000 | false |
| `fw03-bw0p25` | 50.728 | -3.048 | [-5.007, -1.361] | 1.000 | false |
| `fw05-bw0` | 54.211 | 0.435 | [-0.048, 0.803] | 1.000 | false |
| `fw05-bw0p1` | 53.776 | 0.000 | [0.000, 0.000] | 1.000 | false |
| `fw05-bw0p25` | 53.946 | 0.170 | [-0.048, 0.469] | 1.000 | false |
| `fw07-bw0` | 55.469 | 1.694 | [0.497, 2.850] | 1.000 | true |
| `fw07-bw0p1` | 54.789 | 1.014 | [-0.340, 2.286] | 1.000 | false |
| `fw07-bw0p25` | 54.864 | 1.088 | [-0.306, 2.374] | 1.000 | false |
| `fw10-bw0` | 56.503 | 2.728 | [0.762, 4.544] | 1.000 | true |
| `fw10-bw0p1` | 55.980 | 2.204 | [0.510, 3.905] | 1.000 | true |
| `fw10-bw0p25` | 55.578 | 1.803 | [0.014, 3.340] | 1.000 | true |

## Frozen development decision

Selected candidate: `fw10-bw0`

Highest eligible paired mean improvement selected; exact ties use lower turnover, then lower median solver runtime, then candidate_id.

## Main effects

| Factor | Level | Marginal mean | Effect from control level |
| --- | --- | ---: | ---: |
| form_window | 3 | 50.977 | -3.000 |
| form_window | 5 | 53.977 | 0.000 |
| form_window | 7 | 55.041 | 1.063 |
| form_window | 10 | 56.020 | 2.043 |
| bench_weight | 0.0 | 54.350 | 0.468 |
| bench_weight | 0.1 | 53.883 | 0.000 |
| bench_weight | 0.25 | 53.779 | -0.104 |
