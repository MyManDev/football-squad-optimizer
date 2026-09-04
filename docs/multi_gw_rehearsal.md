# Multi-gameweek planning rehearsal

- Contract: `multi_gw_rehearsal_v1`; projection rule `naive_calendar_scaling_v1`
- Season 2024-25; horizon 3 gameweeks; 6 sampled windows
- Shared decision-time candidate pool: top 20 + 8 cheapest per position

**Mean planning advantage: +1.17 net points per window** (planner minus myopic, realized points minus transfer hits).

| Start GW | Planner net | Myopic net | Advantage | Planner hits | Myopic hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| 5 | 159.0 | 155.0 | +4.0 | 0 | 0 |
| 10 | 157.0 | 177.0 | -20.0 | 0 | 0 |
| 15 | 167.0 | 157.0 | +10.0 | 0 | 0 |
| 20 | 160.0 | 153.0 | +7.0 | 0 | 0 |
| 25 | 187.0 | 203.0 | -16.0 | 0 | 0 |
| 30 | 135.0 | 113.0 | +22.0 | 0 | 4 |

The myopic baseline re-projects each week from fresh features, so it holds a
real informational edge; the comparison isolates what committing to a plan
costs or earns under deliberately naive projections. Measurement only: no
promotion, no locked-holdout access.
