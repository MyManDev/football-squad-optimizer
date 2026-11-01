# Entry state readers

These functions read synthetic FPL-shaped documents offline (#983 steps 1 and 2). The
member page does not import them yet. The forwarder's entry bundle reads through them
unchanged in `../forwarder/entryState.ts` (#983 step 3).

| Function                | Python reference                                                                                      |
| ----------------------- | ----------------------------------------------------------------------------------------------------- |
| `readHistory`           | `data.sources.fpl_live.entry_transfer_history`                                                        |
| `readPicks`             | `data.sources.fpl_live.fpl_entry_picks`                                                               |
| `bankedFreeTransfers`   | `live.banking.banked_free_transfers`                                                                  |
| `heldSquadBasis`        | `application.capture_entries.CapturePicksProvider._basis` and `live.free_hit.free_hit_basis_gameweek` |
| `chipStates`            | `application.entries.chip_states`                                                                     |
| `planGameweek`          | `data.sources.fpl_live.next_open_deadline`                                                            |
| `readTransfers`         | `data.sources.fpl_live.entry_transfers`                                                               |
| `readElementPrices`     | `data.sources.fpl_live.element_prices`                                                                |
| `rebuildPurchasePrices` | `live.purchase_prices.rebuild_purchase_prices`                                                        |
| `sellPriceTenths`       | `planning.pricing.sell_price_tenths`                                                                  |
| `sellingInputs`         | `application.entries.held_squad_from_picks` and `planning.pricing.sell_price_tenths`                  |

`readEntry` binds the public entry identity, team name and joining week. The picks reader
also checks the requested gameweek. A bench captain is preserved only with a unique
matching automatic substitution. Missing Free Hit basis picks are refused. An incomplete
transfer history retains the Python model's unknown free-transfer count of one.

`market_value_tenths` includes the bank and is not a selling budget. Purchase-price replay
checks the opening budget, every transfer window, weekly counts and banks, and the final
held squad. Free Hit transfers run on a disposable copy; repurchases keep the latest
purchase price. Only a buy at the exact same microsecond can price a checked sale.

`sellingInputs` applies the accepted selling rule when replay is proved. Otherwise it
preserves the server's explicit `purchase_prices_known: false` fallback: current prices
for each player, capped by the aggregate value from the held picks. It does not label
that fallback as a proved budget. Nothing here constructs or submits a device plan.
The forwarder client and the identity rule that binds a bundle to a device table (the
picks gameweek is the table gameweek minus 1, and the history covers it) are in
`../forwarder/` and `docs/contracts/league_device_plan_v1.md`.

Regenerate the synthetic reference with `python -m scripts.export_entry_state_vectors`.
The Python drift test compares it with current production functions; `state.test.ts` runs
the same inputs through TypeScript. No retained member capture is included.

`python -m scripts.export_entry_price_vectors` exports the purchase-price replay and
selling-rule cases. The drift test and `prices.test.ts` cover the same inputs, including
Free Hit, Wildcard, repurchases, future transfers, ambiguous rows and late joiners.
