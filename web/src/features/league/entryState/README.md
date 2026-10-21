# Entry state readers

These functions read synthetic FPL-shaped documents offline. They are not imported by
the member page or a network client yet (#983 step 1).

| Function              | Python reference                                                                                      |
| --------------------- | ----------------------------------------------------------------------------------------------------- |
| `readHistory`         | `data.sources.fpl_live.entry_transfer_history`                                                        |
| `readPicks`           | `data.sources.fpl_live.fpl_entry_picks`                                                               |
| `bankedFreeTransfers` | `live.banking.banked_free_transfers`                                                                  |
| `heldSquadBasis`      | `application.capture_entries.CapturePicksProvider._basis` and `live.free_hit.free_hit_basis_gameweek` |
| `chipStates`          | `application.entries.chip_states`                                                                     |
| `planGameweek`        | `data.sources.fpl_live.next_open_deadline`                                                            |

`readEntry` binds the public entry identity, team name and joining week. The picks reader
also checks the requested gameweek. A bench captain is preserved only with a unique
matching automatic substitution. Missing Free Hit basis picks are refused. An incomplete
transfer history retains the Python model's unknown free-transfer count of one.

`market_value_tenths` includes the bank and is not a selling budget. Purchase-price replay
and the selling rule remain step 2. Nothing here constructs or submits a device plan.
The forwarder client and its capture/week identity checks remain step 3.

Regenerate the synthetic reference with `python -m scripts.export_entry_state_vectors`.
The Python drift test compares it with current production functions; `state.test.ts` runs
the same inputs through TypeScript. No retained member capture is included.
