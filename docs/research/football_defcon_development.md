# Direct DEFCON tail development results

Measured on 28 September 2026 under the [explicit development scope](football_defcon_development_scope.md).
All 33 scheduled paired weeks completed. Both unchanged comparator heads reproduced
their recorded point MSE and event Brier within 1e-10 at every origin.
The synthetic tests cover shrinkage arithmetic, minute integration,
same-week exclusion, strict settlement cutoff, missing labels and invalid mass.

All means below weight gameweeks equally. The population is outfield players with
known event labels, including nonappearances. Lower losses are better; bias is
mean forecast minus observed event frequency. These are reused development data.

| Season | Arm | Brier | Binary log loss | Bias | Point MSE |
| --- | --- | ---: | ---: | ---: | ---: |
| 2025-26 | Contextual DEFCON | 0.042631 | 0.145190 | -0.004318 | 3.810945 |
| 2025-26 | Frozen v1 | 0.041583 | 0.141695 | +0.001714 | 3.812423 |
| 2025-26 | Direct shrinkage | 0.042097 | 0.144567 | +0.000072 | 3.810876 |
| 2026-27 | Contextual DEFCON | 0.045141 | 0.167841 | +0.000850 | 5.231954 |
| 2026-27 | Frozen v1 | 0.044980 | 0.164309 | -0.000540 | 5.244500 |
| 2026-27 | Direct shrinkage | 0.045689 | 0.171636 | +0.008320 | 5.235885 |

## Position diagnostics

| Season | Position | Direct minus control Brier | Direct minus control point MSE |
| --- | --- | ---: | ---: |
| 2025-26 | DEF | +0.000296 | -0.002027 |
| 2025-26 | MID | +0.000828 | -0.000747 |
| 2025-26 | FWD | -0.000103 | -0.003030 |
| 2026-27 | DEF | +0.001806 | +0.017428 |
| 2026-27 | MID | +0.000069 | -0.030245 |
| 2026-27 | FWD | +0.000016 | -0.000834 |

## Interpretation limits

The direct-tail candidate is rejected for promotion: both Brier and binary log
loss worsen against frozen v1 in both seasons, despite lower total-point MSE.
No candidate is promoted. These measurements do not evaluate squad decisions,
future multi-week outcomes or an independent prospective population. The five
current weeks are a small, dependent, already-read sample. Historical rosters
and the current retrospective capture retain the original study limitations.
This head estimates an event tail, not a full count distribution. It cannot
claim better count likelihood. A lower point loss can mask a worse event loss;
both must remain visible. No parameters were selected from these results.

The first execution failed before scoring because an optional reader for old
local pickles was absent. Comparators were then refitted without new dependencies.
A second execution stopped at current GW2 on the strict parity gate. The final
execution recomputed current causal features with the original method rather
than round-tripping the intermediate feature CSV; all parity checks then passed.
No partial failed execution supplies the reported result. The candidate, priors,
folds and metrics were unchanged. Code and input hashes plus every paired fold
are retained in the [measurement record](football_defcon_development.json).

After measurement, only the runner parity-failure message was line-wrapped for
lint. The record retains both executed and delivered runner hashes; numerical
code and the declared protocol are unchanged.
