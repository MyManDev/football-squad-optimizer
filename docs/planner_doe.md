# Planner control screen

- Contract: `planner_control_screen_v1`; projection rule `naive_calendar_scaling_v1`
- Season 2024-25; windows starting at 5, 10, 15, 20, 25, 30
- Design: one factor at a time around the defaults (horizon 3, hit 4.0, discount 1.0); every variant shares pools, starting squads, and the myopic baseline protocol

| Variant | Horizon | Hit cost | Discount | Windows | Mean advantage | Min | Max | Transfers | Hit pts |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| baseline_h3 | 3 | 4 | 1.00 | 6 | +1.17 | -20.0 | +22.0 | 6 | 0 |
| horizon_2 | 2 | 4 | 1.00 | 6 | +4.83 | -6.0 | +22.0 | 2 | 0 |
| horizon_4 | 4 | 4 | 1.00 | 6 | -3.67 | -31.0 | +21.0 | 11 | 8 |
| hit_free | 3 | 0 | 1.00 | 6 | +5.33 | -9.0 | +24.0 | 23 | 0 |
| hit_8 | 3 | 8 | 1.00 | 6 | +1.17 | -20.0 | +22.0 | 6 | 0 |
| discount_09 | 3 | 4 | 0.90 | 6 | +1.17 | -20.0 | +22.0 | 5 | 0 |

Read: a control whose variant row barely moves the mean advantage does not
deserve a search dimension; a control that moves it belongs in the future
horizon-policy search space. Measurement only; nothing was promoted.
