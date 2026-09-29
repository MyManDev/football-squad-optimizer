# Three-week temporal refinement measurement

Single immutable capture, full player universe and constructed squads. This repeats
development evidence; it is not independent realized performance. Top100 settings
remain user preferences. All protocol choices preceded this run.

Valid pairs: **16/16**. Failed pairs: **0**.
Engineering screen passed: **False**. No production activation.

| Profile | Weeks | Top100 | Case | Control utility | Refined utility | Delta | Raw delta | Gain over own baseline | Hits (control/refined) |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1000 | 3 | 0 | plain | 159.521067 | 159.521067 | +0.000000 | +0.000000 | +0.000000 | 0/0 |
| 1000 | 3 | 20 | plain | 165.654268 | 165.654268 | +0.000000 | +0.000000 | +0.000000 | 0/0 |
| 1000 | 3 | 50 | plain | 179.693840 | 179.693840 | +0.000000 | +0.000000 | +0.000000 | 8/8 |
| 1000 | 5 | 0 | plain | 270.610046 | 270.390363 | -0.219683 | -0.219683 | +0.000000 | 0/0 |
| 1000 | 5 | 20 | plain | 277.051057 | 276.894021 | -0.157036 | +2.729841 | +0.000000 | 0/0 |
| 1000 | 5 | 50 | plain | 304.251568 | 302.048933 | -2.202634 | -5.365244 | +1.166951 | 8/12 |
| 900 | 3 | 0 | plain | 155.911747 | 155.911747 | +0.000000 | +0.000000 | +0.000000 | 0/0 |
| 900 | 3 | 20 | plain | 160.877724 | 160.877724 | +0.000000 | +0.000000 | +0.000000 | 0/0 |
| 900 | 3 | 50 | plain | 167.544444 | 168.901171 | +1.356727 | -5.163177 | +1.356727 | 0/8 |
| 900 | 5 | 0 | plain | 264.755353 | 259.952125 | -4.803228 | -4.803228 | +0.000000 | 0/0 |
| 900 | 5 | 20 | plain | 273.456077 | 273.456077 | +0.000000 | +0.000000 | +1.537885 | 0/0 |
| 900 | 5 | 50 | plain | 286.840052 | 287.944388 | +1.104336 | -7.961948 | +3.488570 | 0/8 |
| 1000 | 5 | 20 | preferences | 280.851467 | 280.100290 | -0.751177 | -0.282437 | +0.934227 | 0/0 |
| 1000 | 5 | 20 | freehit | 280.897667 | 280.897667 | +0.000000 | +0.000000 | +0.000000 | 0/0 |
| 900 | 5 | 20 | preferences | 273.456077 | 273.456077 | +0.000000 | +0.000000 | +0.000000 | 0/0 |
| 900 | 5 | 20 | freehit | 272.660916 | 272.660916 | +0.000000 | +0.000000 | +0.000000 | 0/0 |

Utility is the supplied forecast with the selected Top100 multiplier; raw deltas
rescore exactly the same XI/captain/chip/hit decisions without that multiplier.
Different weights define different preferences, not directly comparable accuracy.

The direct control receives the sum of the baseline and repair search caps. Actual
time can differ, particularly when a baseline proves optimal and skips repair.
The JSON contains all primary/tie/hold diagnostics, failed repairs, accepted steps,
complete squads, transfers, bank and free-transfer paths. A neighborhood optimum
does not certify the unrestricted problem. Selected repaired plans remain FEASIBLE.

This experiment changes no forecasts, fitted constants, default service behavior,
live model or prospective protocol. Acquisition accounting is disabled in both arms; calibrated
information transitions and beyond-five-week forecast supply remain limitations.

See the [method and protocol](triple_repair_protocol.md) and the
[complete record](triple_refinement_measurement.json).

## Interpretation

For 3 weeks, 6 valid pairs: utility gains over 0.1 in 1, losses worse than 0.1 in 0. Raw forecast gains over 0.1 in 0, losses worse than 0.1 in 1.

For 5 weeks, 10 valid pairs: utility gains over 0.1 in 1, losses worse than 0.1 in 5. Raw forecast gains over 0.1 in 1, losses worse than 0.1 in 5.

The refinement accepted 8 of 25 attempted neighborhoods. Local improvement over its own short baseline is a different comparison from beating the longer unrestricted control.

The predeclared screen governs the decision; successful cells do not cancel a blocking loss elsewhere. Three-week neighborhoods can still leave a coordinated change spanning more weeks outside them. The run does not prove that this mechanism explains every loss.

The prior pair-repair experiment had three gains, five losses and eight ties against its own control. It is historical development context, not an identically timed direct competitor in this run. No second wider-search candidate was selected after viewing these outcomes.

Keep the measured implementation opt-in for offline research. Do not choose a Top100 weight, model or default planner from this single reused capture. A future search-policy comparison needs a separately declared case set and must keep a full feasible fallback, report its extra search cost, and retain all losing cases.

## Follow-up boundary

The immutable source manifest and base commit identify the measured code before
subsequent branch integration. No model was refitted or search parameter selected
after this run. In the first losing zero-weight case, all three repairs exhausted
their deterministic limits and remained FEASIBLE. Widening the neighborhood does
not imply solving it. A future separately declared experiment could investigate
carrying the known incumbent as a solver hint; this run only retains it as fallback.
Neither a causal explanation for every loss nor a gain from hints is established.

Measured source content is preserved in `cb3d740f`. Source hashes were captured
from the Windows checkout: thirteen files used CRLF and one used LF. Each hash
was verified against that Git revision with the corresponding newline convention.
Git path lookup uses forward slashes for the recorded Windows-relative paths.
