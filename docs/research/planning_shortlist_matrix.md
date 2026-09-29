# Shortlist across squads, Top 100 preferences and chips

Measured on 28 September 2026 (UTC). Outcome-free development engineering evidence.
One immutable GW6 football v1 forecast covers 667 players and GW6 through GW10.
The actual prior-week Top 100 export passes the production cohort, timestamp,
mapping and 1,100-starter checks. It was captured before this decision snapshot.
This is a newer capture than the original shortlist study, not a rerun of its scores.

## Design fixed before results

Forty paired cases use three constructed squads, never private owner holdings.
Construction budgets are 100.0, 95.0 and 90.0; total starting funds are 100.0,
100.0 and 90.0, with one, two and zero free transfers respectively. Construction
must prove optimality. The complete holdings and banks are in the JSON record.

The core crosses three squads, three Top 100 weights (0, 20, 50) and windows of
three and five weeks. Four remaining offered weights (5, 10, 30, 40) use the
100.0 squad over three weeks. Each squad also receives four first-week forced
chip cases (TC, BB, WC, FH), one keep/avoid/no-hit case, and one save-chips case,
all at weight 20 over five weeks. Forced use tests conditional plan quality,
not optimal chip timing. Save-chips has TC and BB available but forbids spending them.

The unchanged shortlist retains weekly top eight and cheapest five by position,
after applying the actual application Top 100 rule. Held and every named keep/avoid
ID survive selection, including one avoided ID outside the ordinary shortlist.
Avoided IDs remain represented so the planner can validate the original request.

Both arms use 120 wall seconds and 60 deterministic units, plus the same feasible-hold
probe (up to 30 wall seconds and one deterministic unit). Cases run sequentially;
arm order alternates. No parameter sweep or outcome-based case selection occurs.
Wall time covers the solver call and decision audit and is machine-dependent.
It excludes shared input loading and the shortlist construction before each pair;
the ratio is therefore not a measurement of complete API response latency.

Elapsed cost also includes the planner's tie-breaking solve. Primary optimality
and deterministic tie-breaking completion are different claims. Their statuses
and deterministic times are retained separately in each arm's diagnostics.

The predeclared screen requires every pair valid, no weighted regression greater
than 0.1 points over the whole window, and median paired wall ratio at most 0.8.
It is a development screen, not a production promotion rule.

## Results

- Valid pairs: 40/40; failed pairs: 0.
- Weighted regressions greater than 0.1 points: 2.
- Median shortlist/full elapsed-time ratio: 0.2569.
- Predeclared engineering screen: failed.
- Production activation: no. Independent future advantage: not measured.

Each returned decision is re-scored on both original full tables. This includes
the additional TC captain copy, all BB bench points and transfer hits. Weighted
utility is never described as extra forecast points. The optimizer already verifies
squad legality, transfer/bank continuity, free transfers and Free Hit reversion;
the runner additionally checks every keep/avoid/no-hit/save/forced-chip condition.

| Budget | Weeks | Top 100 | Case | Short pool | Full status | Short status | Weighted delta | Base delta | Time ratio |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 100.0 | 3 | 0 | plain | 74 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0471 |
| 100.0 | 3 | 20 | plain | 75 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0767 |
| 100.0 | 3 | 50 | plain | 70 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0700 |
| 100.0 | 5 | 0 | plain | 84 | FEASIBLE | OPTIMAL | +0.2197 | +0.2197 | 0.8343 |
| 100.0 | 5 | 20 | plain | 84 | FEASIBLE | OPTIMAL | +3.9574 | +1.5778 | 0.8613 |
| 100.0 | 5 | 50 | plain | 76 | FEASIBLE | FEASIBLE | +4.2586 | +4.4043 | 0.8242 |
| 95.0 | 3 | 0 | plain | 73 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0483 |
| 95.0 | 3 | 20 | plain | 74 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0281 |
| 95.0 | 3 | 50 | plain | 69 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0514 |
| 95.0 | 5 | 0 | plain | 83 | FEASIBLE | OPTIMAL | +9.6129 | +9.6129 | 0.9189 |
| 95.0 | 5 | 20 | plain | 83 | FEASIBLE | FEASIBLE | +15.6128 | +8.0481 | 0.9818 |
| 95.0 | 5 | 50 | plain | 75 | FEASIBLE | FEASIBLE | +27.9373 | +2.1753 | 0.9779 |
| 90.0 | 3 | 0 | plain | 72 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0127 |
| 90.0 | 3 | 20 | plain | 74 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0190 |
| 90.0 | 3 | 50 | plain | 70 | FEASIBLE | OPTIMAL | +1.0312 | +2.4889 | 0.0486 |
| 90.0 | 5 | 0 | plain | 82 | FEASIBLE | OPTIMAL | +4.8032 | +4.8032 | 0.2073 |
| 90.0 | 5 | 20 | plain | 83 | FEASIBLE | OPTIMAL | +1.6851 | +0.9297 | 0.3537 |
| 90.0 | 5 | 50 | plain | 75 | FEASIBLE | OPTIMAL | +5.2769 | -7.5920 | 0.4019 |
| 100.0 | 5 | 20 | 3xc | 84 | FEASIBLE | OPTIMAL | +5.5713 | +2.6673 | 0.5160 |
| 100.0 | 5 | 20 | bboost | 84 | FEASIBLE | OPTIMAL | +6.3586 | +4.1825 | 0.8414 |
| 100.0 | 5 | 20 | wildcard | 84 | FEASIBLE | FEASIBLE | +13.0413 | +2.5599 | 0.9942 |
| 100.0 | 5 | 20 | freehit | 84 | FEASIBLE | OPTIMAL | -0.3763 | -0.0347 | 0.3894 |
| 100.0 | 5 | 20 | constraints | 85 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0699 |
| 100.0 | 5 | 20 | save | 84 | FEASIBLE | OPTIMAL | +3.9574 | +1.5778 | 0.8202 |
| 95.0 | 5 | 20 | 3xc | 83 | FEASIBLE | FEASIBLE | +15.9037 | +6.3706 | 0.9520 |
| 95.0 | 5 | 20 | bboost | 83 | FEASIBLE | FEASIBLE | +17.4890 | +10.1870 | 1.0799 |
| 95.0 | 5 | 20 | wildcard | 83 | FEASIBLE | FEASIBLE | +12.9588 | +12.8923 | 0.6864 |
| 95.0 | 5 | 20 | freehit | 83 | FEASIBLE | OPTIMAL | +4.1357 | +4.2788 | 0.3065 |
| 95.0 | 5 | 20 | constraints | 84 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0666 |
| 95.0 | 5 | 20 | save | 83 | FEASIBLE | FEASIBLE | +14.5642 | +7.4422 | 0.7608 |
| 90.0 | 5 | 20 | 3xc | 83 | FEASIBLE | OPTIMAL | +4.6341 | +5.2194 | 0.0921 |
| 90.0 | 5 | 20 | bboost | 83 | FEASIBLE | OPTIMAL | +4.5318 | +4.8583 | 0.1018 |
| 90.0 | 5 | 20 | wildcard | 83 | FEASIBLE | OPTIMAL | -0.0697 | +0.1427 | 0.4840 |
| 90.0 | 5 | 20 | freehit | 83 | OPTIMAL | OPTIMAL | -0.1535 | +0.3359 | 0.0374 |
| 90.0 | 5 | 20 | constraints | 84 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0265 |
| 90.0 | 5 | 20 | save | 83 | FEASIBLE | OPTIMAL | +1.5379 | +0.9867 | 0.5414 |
| 100.0 | 3 | 5 | plain | 74 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0419 |
| 100.0 | 3 | 10 | plain | 73 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0396 |
| 100.0 | 3 | 30 | plain | 71 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0277 |
| 100.0 | 3 | 40 | plain | 70 | OPTIMAL | OPTIMAL | +0.0000 | +0.0000 | 0.0235 |

## Cases that block the screen

- Budget 100.0, 5 weeks, weight 20, freehit: weighted delta -0.376266; full FEASIBLE, shortlist OPTIMAL.
- Budget 90.0, 5 weeks, weight 20, freehit: weighted delta -0.153546; full OPTIMAL, shortlist OPTIMAL.

## Limits and decision

An OPTIMAL label on a shortlist proves only that subset. A better incumbent under
a time limit does not prove the full-pool global optimum.
Optimality refers to the planner's scaled objective; reported point deltas use
the independent unrounded rescore, so tiny differences need not imply a different
scaled optimum. Both arms retain their
original bounds, statuses and hold diagnostics in the JSON; failed cases are not
silently discarded or scored as zero. Different weighted settings are different
objectives, so their utilities must not be compared as forecast improvements.

All squads share one capture, model and future calendar. They are constructed
stress cases, not independent managers or season returns. The same lagged Top 100
counts are repeated across future weeks, matching the application rule. This does
not forecast future Top 100 selections, injuries, prices, double gameweeks or blanks.
Starting sale values use the current snapshot prices, with no purchase-price spread.
All three constructed squads share this price assumption and fixture calendar.
No recourse, stochastic multi-chip season policy, model promotion or live default
was added. Broader captures and naturally varied holdings are still needed before
an activation decision; failures of this screen remain reasons to withhold it.

## Descriptive window breakdown

These groups describe the fixed cases, without replacing the overall screen.

| Weeks | Valid pairs | Median time ratio | Worst weighted delta | Worst base delta |
| --- | --- | --- | --- | --- |
| 3 | 13 | 0.0419 | +0.0000 | +0.0000 |
| 5 | 27 | 0.5414 | -0.3763 | -7.5920 |

A weighted gain can accompany a lower base forecast score. That is a preference
tradeoff, not evidence that the forecast model improved. Base deltas are retained
even when the weighted engineering screen passes.
