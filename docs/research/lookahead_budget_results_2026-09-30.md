# Certified lookahead study, 30 September 2026

The registered candidate **failed** its engineering acceptance screen: three of
four pairs were valid and improved forecast utility, while one candidate could
not construct a complete seed within its budget. The twelve conditional cells
were not run. No application integration, default change or model promotion follows.

## Fixed design and source

Protocol: [lookahead_budget_protocol.md](lookahead_budget_protocol.md).
Measured source: `28799953d72e9d9b6d491af0bd25a05da333aa4e`.
Guard and segmented-state source: #905, `832084c2`; producer dependency:
#898, `8d510a03b5bbab63c2b2131d80a6e43749a02bf9`. Owner files were not edited.

The study ran from 19:59:21Z to 20:42:55Z. One local measurement process,
Python 3.13.5, OR-Tools 9.15.6755, numpy 2.5.2 and pandas 3.0.5.
Both arms had a configured deterministic cap of 280 including construction,
certification and the control hold probe. Actual work and elapsed times differ.

Capture: `fpl-live-20260922T214539Z-364991a4f832`. Profiles are fixed
constructed squads, not owner portfolios. Both use bank zero; profile 1000 starts
with one FT, profile 900 with zero. All comparisons use the same full player set,
GW6 through GW19 forecasts, captured prices, preferences and acquisition fee 0.5.

Only archive seasons 2022-23, 2023-24 and 2024-25 and captured settled 2026-27
history were used (60,199 training rows). Both archive reading and hashing were
scoped before access. The locked 2025-26 holdout was not accessed.
The rebuilt five-week forecast matches the first five weeks of the extended
forecast at 1e-10. It differs from the served forecast by up to 1.282157155
player-week points. It is not the live model or a numerical reproduction of #904,
whose exact capture is unavailable locally.

## Results

Scores below are unrounded net forecast points, including hits. Top100 weight is
zero in all measured cells. The display window is separate from the full 14-week
objective.

| Profile | Display | Control full | Candidate full | Full gain | Control window | Candidate window |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 1000 | 3 | 714.631159 | 747.185300 | +32.554141 | 158.016581 | 161.700725 |
| 1000 | 5 | 714.631159 | 747.185300 | +32.554141 | 262.927450 | 268.696218 |
| 900 | 3 | 701.954029 | No complete candidate | Not scored | 156.177324 | Not scored |
| 900 | 5 | 701.954029 | 728.117249 | +26.163220 | 259.554220 | 263.563709 |

The two profile 1000 rows returned the same full paths. They are not independent
samples. All valid full solutions are FEASIBLE, not proven globally optimal.
Bounds for profile 1000 are 796.342 control and 794.413 candidate; profile 900
bounds are 788.516 control and 789.673 candidate. The sequential seed won each
completed seed selection. Final search did not improve its scaled objective.
Thus these observations do not establish that the second seed or final search
adds value. They do not constitute an ablation of either phase.

| Profile/display | Control actual work | Candidate actual work | Control seconds | Candidate seconds |
| --- | ---: | ---: | ---: | ---: |
| 1000/3 | 279.018587 | 263.628403 | 252.235 | 331.350 |
| 1000/5 | 279.018587 | 264.295783 | 250.704 | 377.954 |
| 900/3 | 279.018284 | 95.577797 before failure | 450.790 | 86.605 before failure |
| 900/5 | 279.018284 | 263.586447 | 450.714 | 353.185 |

Solver overshoot is retained: for example the profile 1000/window 5 window-tail
construction used 84.664626 against 84 configured. Equal configured caps are not
equal actual work. No speed improvement claim is made.

## Failure and decision

For profile 900/window 3, all 14 sequential one-week segments finished OPTIMAL.
The other seed's first segment GW6..8 was FEASIBLE at 18.003965 deterministic
units. Its continuation GW9..19 exhausted its 66 cap at 66.000929 and returned
UNKNOWN. This does not prove the continuation infeasible.

The registered method requires both seed paths; it correctly refused a partial
candidate before full certification. There was no retry, budget increase,
sequential-only substitution or revised threshold. All 16 phase records remain,
including the failed construction. The failed arm has no aggregate actual-work
field; the 95.577797 above is the sum of recorded phase work, not a zero or an
imputed cost.

The fixed screen required four valid pairs, at least one gain greater than 0.1
and no loss greater than 0.1. It failed on completeness. The Top100 20/50,
preferences and forced Free Hit extensions are **not run**, not passed tests.
Application activation remains off.

## Decisions and resource use

For profile 1000, the candidate used 14 transfers and no hits versus 18 transfers
and 16 hit points for control. Reacquisitions of previously sold players were 3
versus 4. Final banks were 2 versus 7 tenths, with FT 1 in both. The first transfer
changed from out 17761/in 200834 to out 483067/in 513086; captain 141746 was unchanged.

For profile 900/window 5, the first week was identical: hold, captain 141746,
bank 0 and next FT 1. Control held throughout (zero transfers, final FT 5);
candidate made 13 later transfers, no hits and 4 reacquisitions, ending bank 0/FT 1.
Its displayed-window gain was 4.009489 and tail gain 22.153731. These are
deterministic forecast trade-offs, not evidence that spending future FTs is
better after actual new information arrives.

The tail freezes captured availability and prices and has no observation-based
recourse. GW19 is a chip-period boundary, not the season end. No future outcome
score, confidence interval, calibration improvement, or live success was measured.
Known H3 reserve limitations remain outside this change.

## Additional engineering checks

After the frozen study ended, 39 synthetic checks were added in
`tests/unit/test_planner_segmented_edges.py`. They cover 3/5 weeks, two initial
states, Top100 0/20/50 and explicit blank/double and early/delayed return vectors.
A separate complete 2^window enumeration checks the integer optimum, FT recurrence,
hits, bank and base-versus-preference score separation. These are authored stress
cases, not actual fixtures or calibrated return probabilities.

The boundary ledger verifies FT cap 2 across segments, paid transfers and full-model
certification. A sub-millipoint example verifies that equal integer objectives
can differ slightly in unrounded points: the protection guarantee is at solver
scale. A zero configured budget is refused. Existing tests cover exhausted
certification, incomplete paths, bad sources, dated chips and future information
not entering the first decision. These checks do not reverse the failed screen.

## Evidence identity and next question

Private complete phase/path records are preserved under study identifier
`night60-guarded-study01`. SHA256:
- results: `cfafbd29a2795a06b105757d91c4256862d513d64cdaa1a5977556ed59e19357`
- protocol: `b134c844ed5aebef4eaa5053f62ebb4ad10780b5c5f1267b420f6fbd3f905865`
- summary: `aaec15d2e3acd006353a35e4292647a1ef0186077c85cf3262fcb12b03748c3e`

A future registered method could treat seed construction as optional, preserving
a fully certified feasible path when another construction fails, while charging
all failed work. It must be tested as a new candidate and cannot repair this
screen retroactively. The first question is reliability under fixed resource
limits; speculative RL, ANN or Bayesian search is not justified by this result.

## Notes added after review, 10 October 2026

Apart from restored spacing between words and numbers, no text above changed,
and no number, status, verdict or hash; these notes add context only.

- The phase and path evidence (the results, protocol and summary files
  above) is not committed. Phase-level statements, such as the 66.000929
  continuation and the 84.664626 window-tail construction, can be checked
  only against those files, which this report identifies by hash.
- The committed runner, `scripts/measure_guarded_lookahead.py`, refuses to
  start after its preregistered cutoff of 2026-10-01T05:00Z, so it cannot
  regenerate this report as committed.
- The measured planner and producer are the copies in the measured source:
  develop at `e401d4be` with #905's `832084c2` applied, and #898's producer at
  `8d510a03`. Develop has since changed `src/squadopt/planning` and
  `src/squadopt/application/football_live.py`, so these numbers describe the
  measured source, not the planner on develop.
