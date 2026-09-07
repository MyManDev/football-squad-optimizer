# Season Ledger 2026-27

- Contract: `season_ledger_v1`
- One row per recorded decision; raw entries (decision, projections, report, outcome) live locally under `data/ledger/` with per-file checksums.
- Mode: `live` was decided before its deadline; `replay` was recorded afterwards from a capture taken before that deadline.

| GW | Snapshot | Mode | Solver | Projected | Realized | Error | Transfers | Hits | Chip | Net | Unavailable |
| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |
| 1 | `fpl-live-20260821T143619Z-11bc603a8e1c` | live | OPTIMAL | 56.1 | 26 | -30.1 | 0 | 0 | - | 26 | 96 |

Settled gameweeks: 1; mean realized 26.0; total hits 0; net 26; mean projection error -30.1.

The ledger records; it never promotes. Every live decision uses the operational control.
