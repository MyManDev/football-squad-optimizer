# Football attacking-share sizing

## Frozen before the run

This is forecast sizing for issue #1009 part (a), not an accuracy reading. No
settled outcome, live outcome payload or archive result is read. The served model
and the v1 shadow are unchanged.

The declared population is the existing retained-history companion for capture
`fpl-live-20261002T104314Z-8b70515b9b31`, season 2026-27, decision week 6,
captured at `2026-10-02T10:43:14.825881Z`. Its model is
`football_joint_role_retained_history_v1`. Its companion SHA256 is
`0cd93fc38700757efc28762f4a32a9ccca3b62b53923cdbfde97ad8a7f9e8200`.
The forecast and companion must pass their existing fixture-basis validation.
Other model versions are excluded. This is one capture, not a season estimate.

Let m be the captured availability multiplier, g and a the companion's
unmultiplied goal and assist expectations, and G the 2026-27 goal-point value
(GK 10, DEF 6, MID 5, FWD 4).

- S1 is the sum of `(1 - m) * (G * g + 3 * a)` over decision-week
  player-fixtures, recorded in total and separately for each club.
- S2 is the decision-week gain for each player with `m > 0`. For each attacking
  channel, write s for the existing share and T for the club-fixture sum of
  `m * s`. The conditional candidate share is `s / (s + T - m * s)`.
  Its channel expectation is the base expectation times candidate share / s,
  and its credited expectation applies the player's m once. A zero base share
  has zero attacking expectation and zero gain. S2 sums the credited candidate
  minus base attacking points over that player's decision-week fixtures.
- Go if at least one available player on at least one sized capture gains
  **0.2 expected points or more**, using unrounded values. Otherwise no-go.

This document is committed before any result. The runner's code is also committed
before the measurement, so the result names the exact code revision. The JSON
record names capture, model, input hashes, and whether the companion was rebuilt.
Full player-fixture evidence belongs under ignored `artifacts/`; the small record
includes per-club S1, available-player count, maximum S2, threshold count and go.

For a missing companion, the runner rebuilds into its own evidence directory
using the served forecast's exact gameweeks and training-season selection, with
`role_minutes=True`, `retained_role_history=True`, and no contextual or manager
inputs. The rebuilt forecast must have the served fingerprint. It never writes
to the input artifact root or to `data/`.

The binary club-total assertion needs an owner clarification for the all-absent
case: with every m = 0, applying m once credits zero, even with a positive club
forecast. Sizing follows the stated formula; candidate implementation waits for
that clarification. No shipping decision follows from this forecast-only sizing.
