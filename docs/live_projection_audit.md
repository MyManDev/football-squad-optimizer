# Live projection audit

Contract `live_projection_audit_v1`, season 2026-27, generated 2026-09-18T20:23:35+00:00 from settled capture `fpl-live-20260918T122516Z-cd5c04029774`.
Descriptive only: no gate, no interval, nothing promoted. Bias is realized minus forecast, so a negative bias is a forecast that ran high. "Top per position" is each forecast's own highest forecast players, so those columns describe different players for different forecasts; the paired line under a table uses one set. Protocol: `docs/live_projection_audit_prereg.md`.

## Gameweek 1

Deadline 2026-08-21T17:30:00Z; no capture from before it survives.

**opening-carry-over-v1** (The capture this projection was made from was lost on 2026-09-10, and with it the game's forecast and the unconditional projection. An opening-week model, read for our decided numbers only and never pooled.)

| forecast | players | MAE | bias | MAE, top per position | bias, top per position | rank agreement within position | share of forecast points on players who did not appear |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | 600 | 1.597 | +0.038 | 2.470 | -0.133 | 0.498 | 0.303 |

## Gameweek 4

Deadline 2026-09-12T12:30:00Z; forecasts from `fpl-live-20260912T100000Z-24613792ef57`, 2.5 hours before it.

**phase_c_control_components_v1** (in the ledger as `replay`)

| forecast | players | MAE | bias | MAE, top per position | bias, top per position | rank agreement within position | share of forecast points on players who did not appear |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | 656 | 1.193 | +0.121 | 2.347 | +0.385 | 0.703 | 0.155 |
| ours_unconditional | 656 | 1.271 | +0.042 | 2.380 | +0.348 | 0.670 | 0.202 |
| game | 656 | 1.234 | -0.004 | 2.824 | -0.498 | 0.704 | 0.114 |

Absolute error, ours as decided minus the game's forecast: -0.041 over 656 players, -0.374 over the game's top 40 per position (160 players). One gameweek; players share fixtures, so no interval is given.

**phase-c-component-elite-top100-v1**

| forecast | players | MAE | bias | MAE, top per position | bias, top per position | rank agreement within position | share of forecast points on players who did not appear |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | 656 | 1.194 | +0.117 | 2.349 | +0.372 | 0.703 | 0.155 |
| ours_unconditional | 656 | 1.272 | +0.039 | 2.382 | +0.334 | 0.670 | 0.201 |
| game | 656 | 1.234 | -0.004 | 2.824 | -0.498 | 0.704 | 0.114 |

Absolute error, ours as decided minus the game's forecast: -0.041 over 656 players, -0.373 over the game's top 40 per position (160 players). One gameweek; players share fixtures, so no interval is given.

## Not audited

- Gameweek 2: no capture from before its deadline survives, so neither our projection nor the game's forecast can be read.
- Gameweek 3: no capture from before its deadline survives, so neither our projection nor the game's forecast can be read.

## Pooled

Rests on 1 gameweek(s): [4]. Fewer than 6, so no forecast is called better than another here.

| forecast | players | MAE | bias | MAE, top per position | bias, top per position | rank agreement within position | share of forecast points on players who did not appear |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| ours_decided | 656 | 1.193 | +0.121 | 2.347 | +0.385 | 0.703 | 0.155 |
| ours_unconditional | 656 | 1.271 | +0.042 | 2.380 | +0.348 | 0.670 | 0.202 |
| game | 656 | 1.234 | -0.004 | 2.824 | -0.498 | 0.704 | 0.114 |
