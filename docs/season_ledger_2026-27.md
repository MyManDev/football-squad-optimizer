# Season Ledger 2026-27

- Contract: `season_ledger_v1`
- One row per recorded decision; raw entries (decision, projections, report, outcome) live locally under `data/ledger/` with per-file checksums.
- Mode: `live` was decided before its deadline, from a capture that run took; `replay` was recorded after that deadline, or from a capture the run did not take but named; `roll` records that the squad stood still through a deadline nothing was decided for, with no capture, no projection and no solver, the free transfer carried by the game's own accrual.

| GW | Snapshot | Mode | Solver | Projected | Realized | Error | Transfers | Hits | Chip | Net | Unavailable |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| 1 | `fpl-live-20260821T143619Z-11bc603a8e1c` | live | OPTIMAL | 56.1 | 26 | -30.1 | 0 | 0 | - | 26 | 96 |
| 2 | - | roll | - | - | - | - | 0 | 0 | - | - | - |
| 3 | - | roll | - | - | - | - | 0 | 0 | - | - | - |
| 4 | `fpl-live-20260912T100000Z-24613792ef57` | replay | OPTIMAL | 55.7 | 68 | +12.3 | 3 | 0 | - | 68 | 169 |

Settled gameweeks: 2; mean realized 47.0; total hits 0; net 94; mean projection error -8.9.

The ledger records; it never promotes. Every live decision uses the operational control.
