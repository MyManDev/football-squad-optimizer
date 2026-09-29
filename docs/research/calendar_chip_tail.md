# Dated chip opportunities on a fixed squad

Development measurement, 28 September 2026. Research-only implementation:
`src/squadopt/experiments/calendar_chip.py`. Automatic member chips stay disabled.

## What changed

The older stationary continuation repeatedly sampled the selected window, so its
reservation could never exceed that window's largest sample. This new, separately
named benchmark uses the explicit dated forecast through a chip's captured expiry.
For a single right and fixed squad, deterministic stopping is
`V(t) = max(opportunity(t), V(t+1))`, with zero at expiry. The terminal reserve is
the largest eligible forecast opportunity after the selected window. It can exceed
the window's best week when the supplied future forecast warrants it. More dates
alone are not a reason to hold a chip.

Only one Triple Captain or Bench Boost right is supported. Every eligible date must
be represented; a missing week is unknown and refused, while an explicit known blank
can have zero points. The held squad cannot transfer. Reference lineups must be
proved optimal. Multiple chips, Wildcard, Free Hit and pre-priced rights are refused,
so their interactions are not silently approximated by this benchmark.

## Captured example

The immutable 22 September GW6 study capture supplies fixtures through GW19, captured
availability and chip expiry. No new capture or current job/state is read. The
component CONTROL model and constructed squad are those of the previous forward
study. The extended forecast reproduces all original five-week player forecasts
within 1e-10 before the new tail is used. Archive and training hashes are checked.
Each comparison assumes a single unspent right; it is not an owner's chip history.

| Chip | Window | Decision | Best tail week | Tail value | Proof |
| --- | --- | --- | --- | --- | --- |
| 3xc | 1 | hold | 14 | 6.345381 | OPTIMAL |
| 3xc | 3 | hold | 14 | 6.345381 | OPTIMAL |
| 3xc | 5 | hold | 14 | 6.345381 | OPTIMAL |
| bboost | 1 | hold | 13 | 0.100992 | OPTIMAL |
| bboost | 3 | hold | 13 | 0.100992 | OPTIMAL |
| bboost | 5 | hold | 13 | 0.100992 | OPTIMAL |

The six solves each took less than one second after forecasting. This single
constructed squad has a very weak bench; its small Bench Boost reserve is not a
general chip value. Values are marginal forecast points, not extra realized points.
They are not fitted from future results or evidence that GW13/GW14 will be optimal.

## Limits and acceptance

The forecast holds today's eligibility and rates into the future. Injury recovery,
new team news, rescheduled fixtures, transfers and competing chips can change the
answer. No independent season returns or confidence interval are available. This
does not enable automatic chip strategy in the member API or replace its identity.
The old research strategy's two expected-failure tests remain honest legacy limits.

Ten targeted synthetic checks cover 1/3/5-week hold decisions when future opportunity
is better, expiry, missing dates, known blanks and rejecting chip collisions. The
JSON record preserves all six captured examples and diagnostics. Reproduce with
`scripts/measure_calendar_chip.py` using the immutable component/forward study inputs
and a fresh output directory. No data or production artifact is overwritten.
