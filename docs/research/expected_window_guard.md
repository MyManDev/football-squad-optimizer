# Five-free-transfer expected-window regression

The expected-window planner now returns complete three-week plans for both frozen
five-free-transfer cases. The other 18 member-weeks retained their decisions and
scores exactly. Both local passes used the unchanged Phase 1 inputs and the same
60 deterministic units and 1,800-second wall ceiling per window.
[Frozen inputs](llmopt_phase1/inputs.json) · [Before and after measurements](expected_window_guard.json)

## Accounting and results

Before the change, constructing a candidate week by week used 2.4509869963801267
units in GW8 and 2.62141646695701 in GW9. In both cases the final full-window
tie-break still requested 21.599999930000003 units. The first proposal then raised
`Invalid deterministic-work accounting for expected windows.` Both failures
matched the original Phase 1 record. [Phase 1 full-pool comparison](llmopt_phase1_baseline.md#full-pool-comparison)

| Member-week | First proposal before, actual / cap | First proposal after, actual / cap | Second proposal cap after | Total CP work after / 60 | Result after |
| --- | ---: | ---: | ---: | ---: | --- |
| GW8, 3832237 | 24.058744962167573 / 24 | 24.007660662168053 / 24 | 35.99233933783195 | 59.32772398454239 | FEASIBLE, three weeks |
| GW9, 3832237 | 24.223909707394814 / 24 | 24.001975671201624 / 24 | 35.99802432879838 | 45.41131646670793 | FEASIBLE, three weeks |

The planner accounts for work already consumed before starting a subsequent solve.
CP-SAT can finish a call slightly above its issued deterministic allowance. Both
first-proposal readings after the change fall within the existing 0.01-unit check.
The next proposal received the actual remaining balance. The JSON preserves the
unrounded phase totals, individual CP limits and actuals, and native invocation counts.

| Member-week | Raw starting XI net points | Expected lineup net points | Selection utility |
| --- | ---: | ---: | ---: |
| GW8, 3832237 | 150.3811916955234 | 156.32908353732165 | 156.32908353732165 |
| GW9, 3832237 | 146.40092626953322 | 152.75068489810536 | 152.75068489810536 |

For each of the other 18 cases the original, before and after results agree on
solver status, objective, all three measures above and the weekly canonical
decision digest. That digest includes squad membership, transfers, chip, starting
XI, ordered bench, captain, vice-captain, bank, hits, next free transfers and
weekly raw and expected points. The comparison uses exact equality. The two new
plans have no earlier completed score for a gain calculation.

## Inputs and execution

This replay calls the production `optimize_expected_window` directly with the
Phase 1 full-pool control. It uses the saved `squadopt-deterministic-baseline`
forecast, version `phase_c_control_components_v1`, and the appearance probabilities
and fixture counts frozen at each capture. The GW8 and GW9 football-ready bundles
were unavailable locally. The earlier served-football control for GW6 selected
`fixture_football_candidate`, followed the observed-information route and
completed. Reproducing the operational GW8 and GW9 dispatch would require
the corresponding ready bundles.
[Earlier served-path probe](llmopt_window_budget_probe.md) · [Phase 1 protocol](llmopt_phase1_baseline.md)

Both passes ran serially with one solver thread and zero attempted network
connections. Tests and CI ran outside the measurement intervals. The before pass
made 219 CP-SAT calls and 40 native calls in 1,657.6 seconds. The after pass
made 237 CP-SAT calls and 42 native calls in 1,781.2 seconds, including the
second proposal in both recovered cases. Times sum the measured local case
durations. All reported points come from the frozen forecasts.

## Reproduction

Use the same Python environment for both revisions. On
`b464cd6577c23a99e448a115ccb9c5410357e01c`, save the before results to a
path accessible from both checkouts.

```powershell
$env:PYTHONPATH = 'src'
python -m scripts.measure_expected_window_guard --output ../guard-before.json
```

On `031e02e339612a9fe1661206978ff99f396bc5c5`, compare all 20 cases against
that file. For a single-case reproduction on the before revision, add
`--case gw8-3832237` and give the partial run a separate output path.

```powershell
$env:PYTHONPATH = 'src'
python -m scripts.measure_expected_window_guard --before ../guard-before.json --output ../guard-after.json
```
