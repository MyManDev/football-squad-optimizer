# Live projection audit

Contract `live_projection_audit_v1`, season 2026-27, generated 2026-09-25T20:08:53+00:00 from settled capture `fpl-live-20260922T214539Z-364991a4f832`.
Descriptive only: no gate, no interval, nothing promoted. Bias is realized minus forecast, so a negative bias is a forecast that ran high. "Top per position" is each forecast's own highest forecast players, so those columns describe different players for different forecasts; the paired line under a table uses one set. Protocol: `docs/live_projection_audit_prereg.md`.

## Gameweek 1

Deadline 2026-08-21T17:30:00Z; no capture from before it survives.

**opening-carry-over-v1** (The capture this projection was made from was lost on 2026-09-10, and with it the game's forecast and the unconditional projection. An opening-week model, read for our decided numbers only and never pooled.)

| forecast | players | MAE | bias | MAE, top per position | bias, top per position | rank agreement within position | share of forecast points on players who did not appear |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | 600 | 1.597 | +0.038 | 2.470 | -0.133 | 0.498 | 0.303 |

Forecast points on players who did not appear, as points (players):

| split | bucket | ours_decided |
| --- | --- | ---: |
| all | all | 279.2 (292) |
| position | GK | 45.2 (47) |
| position | DEF | 87.6 (90) |
| position | MID | 105.8 (117) |
| position | FWD | 40.7 (38) |
| price band | under_5.0 | 115.4 (130) |
| price band | 5.0_to_7.5 | 159.1 (161) |
| price band | above_7.5 | 4.8 (1) |
| size of the forecast | under_1.0 | 23.1 (133) |
| size of the forecast | 1.0_to_2.5 | 212.2 (145) |
| size of the forecast | 2.5_and_above | 43.9 (14) |
| our availability rule | named | none |
| our availability rule | not_named | 279.2 (292) |

## Gameweek 4

Deadline 2026-09-12T12:30:00Z; forecasts from `fpl-live-20260912T100000Z-24613792ef57`, 2.5 hours before it.

**phase_c_control_components_v1** (in the ledger as `replay`)

| forecast | players | MAE | bias | MAE, top per position | bias, top per position | rank agreement within position | share of forecast points on players who did not appear |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | 656 | 1.193 | +0.121 | 2.347 | +0.385 | 0.703 | 0.155 |
| ours_unconditional | 656 | 1.271 | +0.042 | 2.380 | +0.348 | 0.670 | 0.202 |
| game | 656 | 1.234 | -0.004 | 2.824 | -0.498 | 0.704 | 0.114 |

Forecast points on players who did not appear, as points (players):

| split | bucket | ours_decided | ours_unconditional | game |
| --- | --- | ---: | ---: | ---: |
| all | all | 130.7 (349) | 180.2 (349) | 105.3 (349) |
| position | GK | 10.3 (51) | 12.6 (51) | 3.0 (51) |
| position | DEF | 48.2 (109) | 63.7 (109) | 43.3 (109) |
| position | MID | 59.5 (146) | 81.8 (146) | 48.5 (146) |
| position | FWD | 12.8 (43) | 22.1 (43) | 10.5 (43) |
| price band | under_5.0 | 60.2 (204) | 74.7 (204) | 38.9 (204) |
| price band | 5.0_to_7.5 | 70.5 (144) | 105.2 (144) | 66.4 (144) |
| price band | above_7.5 | 0.0 (1) | 0.4 (1) | 0.0 (1) |
| size of the forecast | under_1.0 | 27.9 (287) | 57.0 (276) | 17.8 (300) |
| size of the forecast | 1.0_to_2.5 | 77.6 (53) | 90.3 (61) | 60.5 (42) |
| size of the forecast | 2.5_and_above | 25.2 (9) | 32.9 (12) | 27.0 (7) |
| our availability rule | named | 9.8 (178) | 59.2 (178) | 11.9 (178) |
| our availability rule | not_named | 121.0 (171) | 121.0 (171) | 93.4 (171) |

By minutes a gameweek played this season before the deadline:

| forecast | prior minutes | players | appeared | forecast points | realized points | MAE | bias |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | none | 269 | 19 | 46.6 | 31.0 | 0.216 | -0.058 |
| ours_decided | under_30 | 133 | 65 | 119.9 | 118.0 | 0.909 | -0.014 |
| ours_decided | 30_to_60 | 69 | 53 | 119.2 | 139.0 | 1.844 | +0.287 |
| ours_decided | 60_and_above | 185 | 170 | 556.0 | 633.0 | 2.577 | +0.416 |
| ours_unconditional | none | 269 | 19 | 72.3 | 31.0 | 0.309 | -0.153 |
| ours_unconditional | under_30 | 133 | 65 | 134.5 | 118.0 | 1.018 | -0.124 |
| ours_unconditional | 30_to_60 | 69 | 53 | 124.2 | 139.0 | 1.917 | +0.214 |
| ours_unconditional | 60_and_above | 185 | 170 | 562.3 | 633.0 | 2.612 | +0.382 |
| game | none | 269 | 19 | 28.5 | 31.0 | 0.157 | +0.009 |
| game | under_30 | 133 | 65 | 95.6 | 118.0 | 0.899 | +0.168 |
| game | 30_to_60 | 69 | 53 | 113.7 | 139.0 | 1.912 | +0.367 |
| game | 60_and_above | 185 | 170 | 685.8 | 633.0 | 2.789 | -0.285 |

Absolute error, ours as decided minus the game's forecast: -0.041 over 656 players, -0.374 over the game's top 40 per position (160 players). One gameweek; players share fixtures, so no interval is given.

**phase-c-component-elite-top100-v1**

| forecast | players | MAE | bias | MAE, top per position | bias, top per position | rank agreement within position | share of forecast points on players who did not appear |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | 656 | 1.194 | +0.117 | 2.349 | +0.372 | 0.703 | 0.155 |
| ours_unconditional | 656 | 1.272 | +0.039 | 2.382 | +0.334 | 0.670 | 0.201 |
| game | 656 | 1.234 | -0.004 | 2.824 | -0.498 | 0.704 | 0.114 |

Forecast points on players who did not appear, as points (players):

| split | bucket | ours_decided | ours_unconditional | game |
| --- | --- | ---: | ---: | ---: |
| all | all | 130.8 (349) | 180.2 (349) | 105.3 (349) |
| position | GK | 10.3 (51) | 12.6 (51) | 3.0 (51) |
| position | DEF | 48.2 (109) | 63.7 (109) | 43.3 (109) |
| position | MID | 59.5 (146) | 81.8 (146) | 48.5 (146) |
| position | FWD | 12.8 (43) | 22.1 (43) | 10.5 (43) |
| price band | under_5.0 | 60.2 (204) | 74.7 (204) | 38.9 (204) |
| price band | 5.0_to_7.5 | 70.6 (144) | 105.2 (144) | 66.4 (144) |
| price band | above_7.5 | 0.0 (1) | 0.4 (1) | 0.0 (1) |
| size of the forecast | under_1.0 | 27.9 (287) | 57.0 (276) | 17.8 (300) |
| size of the forecast | 1.0_to_2.5 | 77.7 (53) | 90.3 (61) | 60.5 (42) |
| size of the forecast | 2.5_and_above | 25.2 (9) | 32.9 (12) | 27.0 (7) |
| our availability rule | named | 9.8 (178) | 59.3 (178) | 11.9 (178) |
| our availability rule | not_named | 121.0 (171) | 121.0 (171) | 93.4 (171) |

By minutes a gameweek played this season before the deadline:

| forecast | prior minutes | players | appeared | forecast points | realized points | MAE | bias |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | none | 269 | 19 | 46.6 | 31.0 | 0.216 | -0.058 |
| ours_decided | under_30 | 133 | 65 | 119.9 | 118.0 | 0.909 | -0.014 |
| ours_decided | 30_to_60 | 69 | 53 | 119.3 | 139.0 | 1.845 | +0.285 |
| ours_decided | 60_and_above | 185 | 170 | 558.1 | 633.0 | 2.578 | +0.405 |
| ours_unconditional | none | 269 | 19 | 72.3 | 31.0 | 0.309 | -0.153 |
| ours_unconditional | under_30 | 133 | 65 | 134.5 | 118.0 | 1.018 | -0.124 |
| ours_unconditional | 30_to_60 | 69 | 53 | 124.4 | 139.0 | 1.918 | +0.212 |
| ours_unconditional | 60_and_above | 185 | 170 | 564.5 | 633.0 | 2.613 | +0.370 |
| game | none | 269 | 19 | 28.5 | 31.0 | 0.157 | +0.009 |
| game | under_30 | 133 | 65 | 95.6 | 118.0 | 0.899 | +0.168 |
| game | 30_to_60 | 69 | 53 | 113.7 | 139.0 | 1.912 | +0.367 |
| game | 60_and_above | 185 | 170 | 685.8 | 633.0 | 2.789 | -0.285 |

Absolute error, ours as decided minus the game's forecast: -0.041 over 656 players, -0.373 over the game's top 40 per position (160 players). One gameweek; players share fixtures, so no interval is given.

## Gameweek 5

Deadline 2026-09-18T17:30:00Z; forecasts from `fpl-live-20260918T122516Z-cd5c04029774`, 5.08 hours before it.

**phase_c_control_components_v1** (in the ledger as `live`)

| forecast | players | MAE | bias | MAE, top per position | bias, top per position | rank agreement within position | share of forecast points on players who did not appear |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | 659 | 1.120 | +0.224 | 2.163 | +0.387 | 0.739 | 0.153 |
| ours_unconditional | 659 | 1.221 | +0.121 | 2.214 | +0.314 | 0.691 | 0.216 |
| game | 659 | 1.163 | +0.118 | 2.569 | -0.390 | 0.742 | 0.108 |

Forecast points on players who did not appear, as points (players):

| split | bucket | ours_decided | ours_unconditional | game |
| --- | --- | ---: | ---: | ---: |
| all | all | 125.1 (358) | 190.9 (358) | 95.9 (358) |
| position | GK | 9.3 (51) | 12.7 (51) | 2.0 (51) |
| position | DEF | 45.5 (118) | 69.3 (118) | 45.3 (118) |
| position | MID | 58.4 (147) | 86.4 (147) | 38.4 (147) |
| position | FWD | 12.0 (42) | 22.6 (42) | 10.2 (42) |
| price band | under_5.0 | 62.5 (224) | 88.2 (224) | 41.6 (224) |
| price band | 5.0_to_7.5 | 59.0 (132) | 97.6 (132) | 48.2 (132) |
| price band | above_7.5 | 3.5 (2) | 5.1 (2) | 6.1 (2) |
| size of the forecast | under_1.0 | 31.2 (302) | 56.9 (283) | 26.6 (327) |
| size of the forecast | 1.0_to_2.5 | 78.3 (51) | 108.7 (67) | 35.9 (23) |
| size of the forecast | 2.5_and_above | 15.7 (5) | 25.2 (8) | 33.4 (8) |
| our availability rule | named | 9.7 (189) | 75.4 (189) | 10.3 (189) |
| our availability rule | not_named | 115.4 (169) | 115.4 (169) | 85.6 (169) |

By minutes a gameweek played this season before the deadline:

| forecast | prior minutes | players | appeared | forecast points | realized points | MAE | bias |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | none | 253 | 14 | 37.0 | 24.0 | 0.221 | -0.051 |
| ours_decided | under_30 | 151 | 70 | 122.6 | 130.0 | 0.862 | +0.049 |
| ours_decided | 30_to_60 | 76 | 62 | 135.5 | 189.0 | 1.654 | +0.704 |
| ours_decided | 60_and_above | 179 | 155 | 522.4 | 622.0 | 2.383 | +0.556 |
| ours_unconditional | none | 253 | 14 | 62.9 | 24.0 | 0.320 | -0.154 |
| ours_unconditional | under_30 | 151 | 70 | 131.3 | 130.0 | 0.918 | -0.009 |
| ours_unconditional | 30_to_60 | 76 | 62 | 150.5 | 189.0 | 1.851 | +0.506 |
| ours_unconditional | 60_and_above | 179 | 155 | 540.7 | 622.0 | 2.481 | +0.454 |
| game | none | 253 | 14 | 6.4 | 24.0 | 0.119 | +0.070 |
| game | under_30 | 151 | 70 | 103.8 | 130.0 | 0.812 | +0.174 |
| game | 30_to_60 | 76 | 62 | 138.9 | 189.0 | 1.804 | +0.659 |
| game | 60_and_above | 179 | 155 | 638.4 | 622.0 | 2.660 | -0.092 |

Absolute error, ours as decided minus the game's forecast: -0.042 over 659 players, -0.293 over the game's top 40 per position (160 players). One gameweek; players share fixtures, so no interval is given.

## Not audited

- Gameweek 2: no capture from before its deadline survives, so neither our projection nor the game's forecast can be read.
- Gameweek 3: no capture from before its deadline survives, so neither our projection nor the game's forecast can be read.

## Pooled

Rests on 2 gameweek(s): [4, 5]. Fewer than 6, so no forecast is called better than another here.

| forecast | players | MAE | bias | MAE, top per position | bias, top per position | rank agreement within position | share of forecast points on players who did not appear |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | 1315 | 1.157 | +0.172 | 2.255 | +0.386 | 0.721 | 0.154 |
| ours_unconditional | 1315 | 1.246 | +0.082 | 2.297 | +0.331 | 0.681 | 0.209 |
| game | 1315 | 1.198 | +0.057 | 2.696 | -0.444 | 0.723 | 0.111 |

Forecast points on players who did not appear, as points (players):

| split | bucket | ours_decided | ours_unconditional | game |
| --- | --- | ---: | ---: | ---: |
| all | all | 255.9 (707) | 371.1 (707) | 201.2 (707) |
| position | GK | 19.6 (102) | 25.2 (102) | 5.0 (102) |
| position | DEF | 93.7 (227) | 133.0 (227) | 88.6 (227) |
| position | MID | 117.8 (293) | 168.2 (293) | 86.9 (293) |
| position | FWD | 24.8 (85) | 44.7 (85) | 20.7 (85) |
| price band | under_5.0 | 122.7 (428) | 162.9 (428) | 80.5 (428) |
| price band | 5.0_to_7.5 | 129.6 (276) | 202.8 (276) | 114.6 (276) |
| price band | above_7.5 | 3.5 (3) | 5.5 (3) | 6.1 (3) |
| size of the forecast | under_1.0 | 59.1 (589) | 113.9 (559) | 44.4 (627) |
| size of the forecast | 1.0_to_2.5 | 155.9 (104) | 199.1 (128) | 96.4 (65) |
| size of the forecast | 2.5_and_above | 40.8 (14) | 58.1 (20) | 60.4 (15) |
| our availability rule | named | 19.5 (367) | 134.7 (367) | 22.2 (367) |
| our availability rule | not_named | 236.4 (340) | 236.4 (340) | 179.0 (340) |

By minutes a gameweek played this season before the deadline:

| forecast | prior minutes | players | appeared | forecast points | realized points | MAE | bias |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | none | 522 | 33 | 83.6 | 55.0 | 0.218 | -0.055 |
| ours_decided | under_30 | 284 | 135 | 242.6 | 248.0 | 0.884 | +0.019 |
| ours_decided | 30_to_60 | 145 | 115 | 254.7 | 328.0 | 1.744 | +0.506 |
| ours_decided | 60_and_above | 364 | 325 | 1078.4 | 1255.0 | 2.482 | +0.485 |
| ours_unconditional | none | 522 | 33 | 135.1 | 55.0 | 0.314 | -0.154 |
| ours_unconditional | under_30 | 284 | 135 | 265.8 | 248.0 | 0.965 | -0.063 |
| ours_unconditional | 30_to_60 | 145 | 115 | 274.8 | 328.0 | 1.882 | +0.367 |
| ours_unconditional | 60_and_above | 364 | 325 | 1103.0 | 1255.0 | 2.547 | +0.418 |
| game | none | 522 | 33 | 34.9 | 55.0 | 0.139 | +0.039 |
| game | under_30 | 284 | 135 | 199.4 | 248.0 | 0.853 | +0.171 |
| game | 30_to_60 | 145 | 115 | 252.6 | 328.0 | 1.855 | +0.520 |
| game | 60_and_above | 364 | 325 | 1324.2 | 1255.0 | 2.726 | -0.190 |
