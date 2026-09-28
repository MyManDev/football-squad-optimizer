# Frozen football forecasts: cumulative window error

Measured on 28 September 2026. This analysis reuses the saved forecasts from the
[contextual development study](football_contextual_development.md). No model was
retrained or tuned. The owner authorized further 2025-26 development use on this date;
earlier reads remain earlier reads, not retrospectively approved pristine evaluation.

All 72 original fixture point-MSE records reproduce within 1e-10 after archive hash
checks. The added target is each represented player's **sum** of forecast points over
1, 3 or 5 weeks, compared with their summed actual points. Multiple fixtures count
once each. If any fixture label is missing, that player's whole window is excluded
from both arms; missing results are never replaced by zero.

Six fixed origins per season (GW11, 15, 19, 23, 27, 31) receive equal weight.
The final historical calendar and constructed roster remain retrospective inputs.
The population is players represented in the frozen fixture forecasts, not every
possible roster member. Overlapping windows are not independent samples. These are
descriptive development losses, not prospective promotion or transfer-policy returns.

## Results

Squared error of summed player points; lower is better. Delta is contextual minus v1.

| Season | Weeks | v1 | Contextual | Delta |
|---|---:|---:|---:|---:|
| 2024-25 | 1 | 3.438824 | 3.462651 | +0.023827 |
| 2024-25 | 3 | 15.080870 | 15.113109 | +0.032238 |
| 2024-25 | 5 | 29.633958 | 29.935048 | +0.301090 |
| 2025-26 | 1 | 3.686127 | 3.640555 | -0.045572 |
| 2025-26 | 3 | 15.574015 | 15.522598 | -0.051418 |
| 2025-26 | 5 | 31.854902 | 31.935211 | +0.080309 |

Contextual v3 is worse at every window in 2024-25. In 2025-26 it improves
the one- and three-week totals slightly, but loses at five weeks. There is no
consistent multi-season, multi-window case for replacing v1. No model or window is
selected after inspecting these results, and production defaults are unchanged.

A sum MSE cannot be compared directly across window lengths: its target grows with
the window and includes cross-week error covariance. The record also reports MAE,
signed bias and MSE of the per-week average (sum MSE divided by window squared).
A smaller normalized error over a longer window does not prove a better plan.

## Coverage and reproduction

| Season | Weeks | Missing fixture labels | Incomplete player windows excluded |
|---|---:|---:|---:|
| 2024-25 | 1 | 0 | 0 |
| 2024-25 | 3 | 8 | 7 |
| 2024-25 | 5 | 26 | 10 |
| 2025-26 | 1 | 0 | 0 |
| 2025-26 | 3 | 15 | 10 |
| 2025-26 | 5 | 39 | 13 |

Counts sum the six origins once per arm; both arms use identical keys and exclusions.
All per-origin counts, losses, protocol and hashes are in the
[machine-readable record](football_window_totals.json). The saved forecast files and
analysis source are hashed on this run; original fixture-loss parity is checked
separately and is not a claim that historical roster/calendar snapshots were verified.

Run `python scripts/analyze_football_windows.py --study <saved-contextual-study>`
`--archive <archive-root> --output <fresh-directory>`. The runner preserves old
evidence by refusing an existing output directory. Synthetic tests cover cross-fixture
error cancellation, whole-player exclusion and invalid or unequal forecast keys.
