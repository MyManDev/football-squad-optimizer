# Bounded single-swap planner comparison

Measured 3 October 2026.

The optional first-week swap improves both prespecified autosub cases by 1.6 expected points over their retained original plans. All five control cases preserve the original utility. A synthetic Top100 case gains 1.2 on the selection scale and 0.8 on the underlying forecast scale. This establishes a bounded synthetic opportunity, not real FPL gains or a global optimum.

The run uses source `a069e5df9561ac0c820814a7b557f953227e59a6` and the frozen revision2 protocol. Each case runs the original 40/60 CP proposals once, preserving both scored outputs. After they complete, the extension may use their actual remaining CP allowance for one extra full-window solve. It ranks legal same-position swaps using a held-lineup multiplier proxy, then fixes only the chosen first squad. Later transfers remain free. Final selection compares all complete candidates on the same expected utility and retains the original winner on ties.

| Case | Weeks / initial FT | Original | Selected | Change | Actual CP | Score calls |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Autosub opportunity | 3 / 1 | 450.6 | 452.2 | +1.6 | 0.022330 | 1,153 |
| Autosub opportunity | 5 / 1 | 751.0 | 752.6 | +1.6 | 0.073099 | 1,921 |
| Certain appearances | 3 / 1 | 450.0 | 450.0 | 0 | 0.017394 | 769 |
| Forced first Free Hit | 3 / 1 | 450.6 | 450.6 | 0 | 0.012854 | 768 |
| Forced first Wildcard | 5 / 1 | 751.0 | 751.0 | 0 | 0.050872 | 1,280 |
| Keep and avoid | 3 / 1 | 447.6 | 447.6 | 0 | 0.002500 | 768 |
| No hits | 3 / 0 | 449.6 | 449.6 | 0 | 0.011488 | 768 |
| Top100 selection weight 20 | 5 / 5 | 751.0 | 752.2 | +1.2 | 0.070658 | 1,921 |

The input has 15 held players and two alternatives, constant prices, distinct clubs, bank 10 and no terminal bonuses. Only one starting defender has uncertain appearance, q = 0.5; points are already unconditional. Upgrading a reserve can therefore beat the original midfield upgrade through legal autosub value. The certain-appearance control removes that opportunity. Keep/avoid and no-hits block the added move, while a forced first-week Free Hit or Wildcard disables the extension before an extra score or solve.

In the two opportunity cases, DEF6 is sold for 50 and DEF16 bought for 60. The first two weeks score 151 each. In week 3, two free transfers sell DEF16/MID12 and buy DEF6/MID17 for a bank-neutral switch; later weeks score 150.2. This gives 452.2/752.6. With initial FT 5, the weighted case switches in week 2: week 1 scores 151.4 in selection utility but 151.0 in base points. Its totals are 752.2 selection and 751.8 base, against 751.0 for the original. The preference does not create extra predicted real points.

These paths differ from the earlier separately funded witness, which fixed DEF7 to DEF16 in every week and scored 453/755, gains 2.4/4. Those larger gains are not results of this first-week-only route and its diagnostic cost is separate.

The common CP caps remain 5 for three weeks and 10 for five, 55 across this matrix. Actual work is 0.261194 units: 0.213205 for the original proposals and 0.047989 for three optional completions. Lineup work increases deliberately from 256*W to at most 384*W+1 calls. Actual calls are 9,348 versus 7,680 for the originals, below the new matrix cap 11,528; 17,787 appearance states are recorded. Total elapsed time is 8.815 seconds. This is not an equal-total-work or equal-time comparison, and no expanded 192-per-week control was run.

Independent receipt review reconstructed 90 plan-weeks, including both originals and each selected path. Roles, formation, bank, FT, hits, Free Hit restoration and the closed-form synthetic scoring agree; maximum point discrepancy is 1.14e-13. All 16 retained-output value digests and 11 source plus 2 helper hashes match. No material core-code defect was found in the narrow read-only review.

Acceptance covers these eight synthetic cases. The protocol's separate variable-price lot/FH regression gates require their own test receipt, and this nominal route does not establish observed-news branch fairness. The [compact evidence record](football_single_swap_2026_10_03.json) preserves paths, hashes, work and limits. No new solver, fit, test, raw dataset or live action was used to prepare this report.
