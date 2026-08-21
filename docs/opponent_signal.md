# Opponent Signal

- Contract: `opponent_signal_v1`
- Grain: `season/gameweek/club`
- Seasons: 2020-21, 2021-22, 2022-23, 2023-24, 2024-25

The Dixon-Coles rating refitted once per gameweek, at that gameweek's first kickoff, and recorded as the attacking and defensive signal it implies for each club. This is an input a declared candidate would read; it decides nothing on its own.

## Coverage

| | Club-gameweeks |
| --- | ---: |
| In the calendar | 3620 |
| Carrying a signal | 3604 |
| Without a signal | 16 |
| …of which each season's opening gameweek | 16 |

Every uncovered cell is an opening gameweek, which is the only honest answer: a rating needs a match before it can rate anybody. Those rows are already outside the learned fit, because the shifted per-90 feature is missing there too — so the signal's coverage costs the fit nothing.

Rating controls fell back to the documented defaults for 2020-21, which has no earlier season to select on. No fold is judged in that season — it is loaded so carry-over has a completed season to read — so the fallback cannot reach a measured claim.

## Reproduction

```powershell
.venv\Scripts\python -m scripts.build_opponent_signal
```

The table itself stays under `artifacts/`: it is the per-fold expansion behind this record, which [ADR 0003](architecture/decisions/0003-measurement-artifacts.md) routes away from the repository.
