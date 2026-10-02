# Certified incumbent hints: paired development measurement

The same full-pool adjacent-pair repair runs with and without a certified incumbent hint. Both arms use the fixed protocol and configured budgets. This is one reused capture with constructed squads, not independent realized performance or forecast calibration.

Valid pairs: **16/16**. Engineering screen passed: **False**. No production activation.

| Profile | Weeks | Top100 | Case | Control utility | Hinted utility | Utility delta | Raw delta | Hits (control/hinted) |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |
| 1000 | 3 | 0 | plain | 159.521067 | 159.521067 | +0.000000 | +0.000000 | 0/0 |
| 1000 | 3 | 20 | plain | 165.654268 | 165.654268 | +0.000000 | +0.000000 | 0/0 |
| 1000 | 3 | 50 | plain | 179.693840 | 179.693840 | +0.000000 | +0.000000 | 8/8 |
| 1000 | 5 | 0 | plain | 270.390363 | 270.390363 | +0.000000 | +0.000000 | 0/0 |
| 1000 | 5 | 20 | plain | 278.902540 | 278.902540 | +0.000000 | +0.000000 | 0/0 |
| 1000 | 5 | 50 | plain | 302.087785 | 302.087785 | +0.000000 | +0.000000 | 12/12 |
| 900 | 3 | 0 | plain | 155.911747 | 155.911747 | +0.000000 | +0.000000 | 0/0 |
| 900 | 3 | 20 | plain | 160.877724 | 160.877724 | +0.000000 | +0.000000 | 0/0 |
| 900 | 3 | 50 | plain | 169.030316 | 169.030316 | +0.000000 | +0.000000 | 8/8 |
| 900 | 5 | 0 | plain | 264.506684 | 264.506684 | +0.000000 | +0.000000 | 0/0 |
| 900 | 5 | 20 | plain | 273.211543 | 273.211543 | +0.000000 | +0.000000 | 0/0 |
| 900 | 5 | 50 | plain | 287.289810 | 287.289810 | +0.000000 | +0.000000 | 0/0 |
| 1000 | 5 | 20 | preferences | 279.166063 | 279.166063 | +0.000000 | +0.000000 | 0/0 |
| 1000 | 5 | 20 | freehit | 280.897667 | 280.897667 | +0.000000 | +0.000000 | 0/0 |
| 900 | 5 | 20 | preferences | 273.456077 | 273.456077 | +0.000000 | +0.000000 | 0/0 |
| 900 | 5 | 20 | freehit | 272.660916 | 272.660916 | +0.000000 | +0.000000 | 0/0 |

## Interpretation and limits

Using the predeclared 0.1 threshold, weighted utility has 0 gains, 0 losses and 16 ties. Raw forecast points have 0 gains, 0 losses and 16 ties. Different Top100 weights express different user preferences, not comparable accuracy.

The baseline objective differs between arms in 0 valid pairs. Configured deterministic and phase wall caps are equal; actual work and all baseline/repair diagnostics are retained. Certification is charged within each hinted repair cap. A neighborhood optimum is not a full-horizon proof.

The screen requires all 16 pairs valid, no incumbent regression, at least one utility gain over 0.1 and no utility loss over 0.1. It is applied unchanged. Losing and failed cases are retained; no parameters or case selection were changed after viewing results.

Acquisition accounting is disabled in both measurement arms. The separately delivered live accounting adapter therefore has no measured interaction with this hint study. Market prices stay frozen. The longer producer horizon in #898 and the two existing chip-reservation H3 failures are outside this evidence. No claim about a learned MDP, future outcomes, model promotion or the best Top100 weight follows.

Measured source: `2ba927fb3abb5f697059fab9a91cb21f89ca3315`. Every source hash was checked against that revision with its recorded LF/CRLF convention. The [complete record](incumbent_refinement_measurement.json) includes inputs, cases, budgets, returned repair records, failed-arm errors and source identities.

## What the trace establishes

Both arms return exactly the same complete paths in all 16 cases, including the same
28 total hit points across the case set. Seven baselines already prove the scaled
full-horizon optimum and skip repair. In the other nine cases, each arm attempts
34 neighborhoods, proves every restricted scaled problem OPTIMAL and accepts
15 improvements over its own baseline. The candidate records 34 certified hints;
the control records zero. The treatment was exercised.

Thus this comparison measures hints where the unhinted pair repairs already
finish their local optimization. Hints add no plan-quality gain here. A restricted
optimum still cannot prove that a change spanning more weeks would not help. The
result does not establish that hints are ineffective under every neighborhood or
budget. A different search space would need a separately declared comparison;
this run did not choose one after looking at its results.

The predeclared improvement screen fails because it requires a positive gain.
Keep the interface opt-in for reproducible research; do not enable it in the
served planner from this evidence. Timing is retained as a resource diagnostic,
not an alternative reason to promote a candidate that failed the quality screen.
