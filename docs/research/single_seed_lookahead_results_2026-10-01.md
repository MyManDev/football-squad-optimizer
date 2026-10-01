# Single-seed certified lookahead study, 1 October 2026

The preregistered single-seed candidate passed the engineering screen in all
16 paired comparisons. Every candidate returned a valid, fully certified path
and improved the matched control's weighted forecast utility by more than 0.1.
This is reused development evidence, not independent future performance or a
live model promotion. The original two-seed experiment remains rejected.

## Design and identity

Protocol: [single_seed_lookahead_protocol.md](single_seed_lookahead_protocol.md),
committed at 82a13398 before implementation and measurement. Measured source:
`db77461eda03eb4a5f886a28883264c6fa225994`. Guard/state adapter: #905 at 832084c2.
Producer dependency: #898 at 8d510a03b5bbab63c2b2131d80a6e43749a02bf9;
its owner files and the #904 measurement lane were not changed.

One process ran from 2026-09-30T22:00:23Z to 2026-10-01T00:39:40Z. Python 3.13.5,
OR-Tools 9.15.6755, numpy 2.5.2 and pandas 3.0.5. Candidate: fourteen sequential
one-week constructions with a combined deterministic cap 28, then one full-model
guarded solve with cap 252, including certification. No second construction,
intermediate polish or extra candidate hold probe. Control: 279 plus hold 1.
Both configured totals are 280; actual work differs and overshoot is retained.
The old two_seed_v1 runner default remains unchanged; single_seed_v1 is explicit.

Capture `fpl-live-20260922T214539Z-364991a4f832`, 60,199 training rows. Only
2022-23, 2023-24, 2024-25 archive history plus captured settled 2026-27 history was
used. Archive reading and hashing were restricted before access; the locked
2025-26 holdout was not accessed. Rebuilt five-week prefix parity passed at 1e-10,
and all forecast/input/core-source identities matched the original study before
any solve. Fourteen-week forecast fingerprint:
`96d0159bdef60ecbc277e13ecae9fccb647002eb5bd9b1b250fbb81c85046345`.
It differs from the served forecast by up to 1.282157155 player-week points.
This is neither the live forecast nor a numerical reproduction of #904, whose
exact capture is unavailable locally.

The fixed constructed profiles 1000 and 900 both start with bank 0 and respectively
FT 1 and FT 0. They are not owner portfolios. Initial historical acquisition lots
were not supplied in these states; current holdings use the supplied sale-price
basis, and subsequent acquisitions have known lots. Known initial-lot behavior
is covered separately by controlled tests, not established by these two profiles.
Both arms use the same full roster, explicit GW6..19 forecast, captured prices
and availability, fee 0.5, discount 1 and bench 0. No future price/injury update or
stochastic recourse policy is measured. Preferences keep the highest held
outfield player, prohibit hits and save chips. Free Hit cases force GW6 in both
arms; they test conditional legality, not optimal chip timing.

## Forecast utility

Deltas below are candidate minus matched control, rounded only for display.
Full means 14 weeks; window means the user's 3/5-week display. Base excludes the
Top100 preference weighting; both net measures include hit costs. Different
weights define different objectives and must not be compared as model accuracy.

| Profile | Window | Top100 | Mode | Weighted full gain | Base full gain | Weighted window gain | Base window gain | Base tail gain |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| 1000 | 3 | 0 | plain | +32.554141 | +32.554141 | +3.684144 | +3.684144 | +28.869997 |
| 1000 | 5 | 0 | plain | +32.554141 | +32.554141 | +5.768768 | +5.768768 | +26.785373 |
| 900 | 3 | 0 | plain | +26.163220 | +26.163220 | +2.216091 | +2.216091 | +23.947129 |
| 900 | 5 | 0 | plain | +26.163220 | +26.163220 | +4.009489 | +4.009489 | +22.153731 |
| 1000 | 3 | 20 | plain | +42.515289 | +34.639856 | +3.923720 | +3.370032 | +31.269824 |
| 1000 | 3 | 50 | plain | +97.432329 | +18.471446 | +16.099316 | +1.707817 | +16.763629 |
| 1000 | 5 | 20 | plain | +42.515289 | +34.639856 | +7.634796 | +5.837173 | +28.802683 |
| 1000 | 5 | 50 | plain | +97.432329 | +18.471446 | +29.466395 | +2.911310 | +15.560136 |
| 900 | 3 | 20 | plain | +27.351720 | +23.553765 | +2.018165 | +2.095168 | +21.458597 |
| 900 | 3 | 50 | plain | +49.234658 | +19.751440 | +2.384639 | +1.034128 | +18.717312 |
| 900 | 5 | 20 | plain | +27.351720 | +23.553765 | +5.456654 | +5.426813 | +18.126952 |
| 900 | 5 | 50 | plain | +49.234658 | +19.751440 | +5.573984 | +2.693212 | +17.058228 |
| 1000 | 5 | 20 | preferences | +34.686663 | +29.661588 | +8.834850 | +7.258227 | +22.403361 |
| 1000 | 5 | 20 | freehit | +42.018077 | +33.381743 | +9.921826 | +6.862095 | +26.519648 |
| 900 | 5 | 20 | preferences | +23.421127 | +21.975475 | +7.737061 | +7.997743 | +13.977732 |
| 900 | 5 | 20 | freehit | +31.265456 | +26.348534 | +7.101837 | +5.897897 | +20.450637 |

The core 4/4 and expanded 16/16 gates passed, with zero losses greater than 0.1.
All full-model results were FEASIBLE, not globally optimal. Each of the six plain
profile/weight combinations returned identical serialized full paths at 3 and 5
weeks in both arms. These paired displays are not independent samples.
No Top100 weight is selected or recommended from this reused capture.

In every candidate, the final scaled objective equaled the certified sequential
seed. The long final search produced no measured scaled-score improvement.
Certification still establishes full-path feasibility against the original
state; this observation is not an independent ablation proving that the final
search can always be removed. Integer-objective protection does not assert an
identical raw decimal score: coefficients are rounded in the solver. For example,
profile 1000/weight 0 has certified/final scaled 747.187 and raw 747.185300.

## Budget and solver evidence

All 256 recorded phases were complete, met the preregistered early-stop fairness
rule and had known actual cost. All 32 arm totals equal the sum of their phases.
The fairness flag does not mean strict actual equal work or a strict cap.
Total recorded work across all arms was 8720.779083 deterministic units.

| Profile/window/weight/mode | Control work | Candidate work | Control seconds | Candidate seconds | Control bound | Candidate bound | Certified seed / final scaled |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1000/3/0/plain | 279.018587 | 263.625134 | 249.636702 | 240.390796 | 796.342000 | 794.413000 | 747.187000 |
| 1000/5/0/plain | 279.018587 | 263.625134 | 251.926085 | 239.566568 | 796.342000 | 794.413000 | 747.187000 |
| 900/3/0/plain | 279.018284 | 263.576892 | 446.316894 | 343.718062 | 788.516000 | 789.673000 | 728.116000 |
| 900/5/0/plain | 279.018284 | 263.576892 | 451.581933 | 356.300838 | 788.516000 | 789.673000 | 728.116000 |
| 1000/3/20/plain | 279.022757 | 263.452421 | 203.060265 | 226.709938 | 845.883000 | 838.557000 | 776.946000 |
| 1000/3/50/plain | 279.834493 | 263.284392 | 323.614967 | 310.438316 | 929.867000 | 916.356000 | 892.217000 |
| 1000/5/20/plain | 279.022757 | 263.452421 | 203.105164 | 226.295247 | 845.883000 | 838.557000 | 776.946000 |
| 1000/5/50/plain | 279.834493 | 263.284392 | 322.233662 | 310.713065 | 929.867000 | 916.356000 | 892.217000 |
| 900/3/20/plain | 279.018253 | 264.261353 | 473.586269 | 329.569700 | 836.246000 | 837.637000 | 749.775000 |
| 900/3/50/plain | 279.018893 | 265.267548 | 256.207541 | 247.604519 | 924.710000 | 919.744000 | 802.491000 |
| 900/5/20/plain | 279.018253 | 264.261353 | 471.761323 | 326.474409 | 836.246000 | 837.637000 | 749.775000 |
| 900/5/50/plain | 279.018893 | 265.267548 | 257.766439 | 239.283958 | 924.710000 | 919.744000 | 802.491000 |
| 1000/5/20/preferences | 279.021784 | 281.071124 | 243.441043 | 230.234229 | 840.552000 | 835.536000 | 779.157000 |
| 1000/5/20/freehit | 279.016581 | 263.860560 | 415.963214 | 209.660629 | 841.098000 | 839.301000 | 776.451000 |
| 900/5/20/preferences | 279.021701 | 278.437905 | 196.362050 | 242.592829 | 830.028000 | 829.757000 | 749.775000 |
| 900/5/20/freehit | 279.857968 | 263.693447 | 259.173559 | 367.817934 | 801.640000 | 829.568000 | 756.595000 |

Profile 1000/5/20/preferences used 281.071124 versus nominal 280, an overshoot of
1.071124 (0.383%). Its control used 279.021784. The candidate's sequential phases
summed 28.150118 against 28; final certification/search used 252.921006 against 252.
Other smaller phase overshoots are also retained in the evidence. No cell was
retried, dropped or retuned after seeing this. Equal configured budgets are not
equal actual work, and there is no speed claim.

## Decision and resource audit

Only one row per identical 3/5 full path is shown. Every pair below is
control/candidate. Permanent transfers exclude Free Hit movements; temporary
Free Hit changes are separate. Reacquisitions count incoming players previously
sold permanently, excluding Free Hit restoration. Bank uses integer tenths.

| Profile/weight/mode | Permanent transfers | Temporary FH changes | Hit points | Reacquisitions | Final bank | Final FT | First transfer control | First transfer candidate |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1000/0/plain | 18/14 | 0/0 | 16/0 | 4/3 | 7/2 | 1/1 | 17761 to 200834 | 483067 to 513086 |
| 900/0/plain | 0/13 | 0/0 | 0/0 | 0/4 | 0/0 | 5/1 | Hold | Hold |
| 1000/20/plain | 1/14 | 0/0 | 0/0 | 0/4 | 22/19 | 5/1 | Hold | 483067 to 513086 |
| 1000/50/plain | 15/15 | 0/0 | 4/4 | 3/3 | 3/2 | 1/1 | 226597 to 575476 | 226597 to 487838 |
| 900/20/plain | 0/13 | 0/0 | 0/0 | 0/2 | 0/1 | 5/1 | Hold | Hold |
| 900/50/plain | 0/13 | 0/0 | 0/0 | 0/4 | 0/1 | 5/1 | Hold | Hold |
| 1000/20/preferences | 14/14 | 0/0 | 0/0 | 4/4 | 2/5 | 1/1 | 226597 to 223827 | 483067 to 513086 |
| 1000/20/freehit | 1/13 | 0/10 | 0/0 | 0/4 | 22/19 | 5/1 | freehit (0 changes) | freehit (10 changes) |
| 900/20/preferences | 13/13 | 0/0 | 0/0 | 2/2 | 39/1 | 1/1 | Hold | Hold |
| 900/20/freehit | 6/12 | 2/6 | 0/0 | 1/1 | 18/3 | 1/1 | freehit (2 changes) | freehit (6 changes) |

All first-week captains are 141746. Both Free Hit cases restore the permanent
state through the existing adapter and are fully recertified from the original
state. Later bank/FT differences reflect different legal transfers, not a claim
of equal end resources. Candidate changes can spend transfer flexibility that
controls retain; there is no terminal FT price or unseen-future option value.
No result establishes an optimal real-world chip date or stochastic MDP policy.

## Comparison and application decision

The [original two-seed report](lookahead_budget_results_2026-09-30.md) is unchanged:
three valid pairs and one incomplete candidate, hence FAIL. Its second seed
returned UNKNOWN in profile 900/window 3; UNKNOWN was not proof of infeasibility.
The preregistered single-seed follow-up removes that extra failure dependency and
completes that cell. The three previously valid candidate paths are unchanged;
the recovered 900/window 3 path matches the prior valid 900/window 5 path. This is
completion evidence, not discovery of a superior path to those prior candidates.

No additional production adapter is warranted in this package. Existing
plan_in_segments and optimize_with_lookahead already provide the narrow opt-in
construction and full-path protection seams. The current football artifact
reader requires the available five-week horizon; this research uses an explicit
fourteen-week artifact from the owner producer dependency. Production strategies
also have different status and budget contracts. Adding another wrapper would
not resolve those boundaries. No application default, user 3/5-week choice or
Top100 selection changed. No model promotion, deployment or backend restart.

Before a product integration, agree an owner-produced extended-forecast contract
and an interactive solve budget, then preregister an independent prospective
comparison with known acquisition lots, actual decision constraints and bounded
resource accounting. The observed absence of final-search gains motivates a
separate certification-only ablation, not an unregistered sweep tonight. Preserve
base/weighted and window/tail reporting; evaluate FT optionality and later forecast
updates without reusing these outcomes to choose the winning configuration.

## Validation and limits

At measured source db77461e: 37 focused tests passed, including actual tiny 14-week
old/new call paths, budget accounting, invalid-seed rejection, certification
fallback and changed-reference refusal before solving. Full Python: 7,714 passed,
15 skipped, two existing H3 expected failures. Ruff checked 1,230 files, mypy 358
configured source files and all six architecture contracts passed. The research
runner is outside the configured mypy/import graph; no broader proof is claimed.
Web: 1,582 passed and two skipped; 153 browser tests passed with two workers.
Generated types, lint, formatting, typecheck, build and deployment-asset/bundle
checks passed. These exercise controlled application/browser behavior, not live
fourteen-week integration. The existing H3 chip-reserve limitations remain.

All 18 recorded source hashes were unchanged after measurement. Results were
independently audited for phase costs, full-path identity, integer non-regression,
first actions, hits, bank/FT and temporary versus permanent transfers. No new
source changed during measurement. Remote CI for this report's delivery must be
verified on the final pushed commit; earlier CI is not substituted.

Evidence hashes (SHA256; raw operational files remain in the local study record):

| Artifact | SHA256 |
| --- | --- |
| results.json | `d2ab43ab14b081901a85f7d7ee825769172901fb95607ed8359dbb259778f925` |
| protocol.json | `c977b45814d23b9a182b9093c2ff1d62957f8d60a1c9e5aa691e60f0cae5de53` |
| summary.json | `4f863e06a815face00a793ebcf66806d5063cb99eb2c007a65dc5e3068876ab5` |
| reference-check.json | `b5ed75f69a114390ddde926c50481d4eaa1712faab3a6170f1e71a36e6238e08` |
