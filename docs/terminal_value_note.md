# The GP lost to four constants, everywhere. Why that is worth having on record.

`terminal_value_study.md` is a clean negative: the pre-registered gate asked the Gaussian
process to beat the constants-plus-average baseline pooled and in at least three of four
held-out seasons, and it lost **pooled (−22.19 MAE) and in all four** (−12 to −35). The
constants stand, exactly as the pre-registration said they would.

## Why it lost — the mechanism, not an excuse

1. **The baseline is quietly excellent.** "Remaining weeks × the training seasons' mean
   weekly net" explains almost all of the target by construction — the target *is* a sum
   of weekly nets, and week-to-week variation mostly averages out over a remaining-season
   horizon. Beating it requires the *state* (bank, sell value, transfers, chips) to carry
   information about future scoring, and at this grain it mostly does not.
2. **Season-level shift is the dominant error, and the GP cannot see it.** The baseline's
   own MAE ranges from 58 (2022-23) to 107 (2024-25): seasons score at different levels,
   and under leave-one-season-out *neither* predictor knows the held-out season's level.
   The baseline degrades gracefully (a wrong constant); the GP, fitted to three seasons'
   levels, extrapolates its nonlinearity into the fourth and degrades worse.
3. **The kernel says overfit out loud.** The fitted length-scale on `remaining_weeks` is
   0.441 standard deviations — the GP bent itself around the training seasons' week-by-week
   idiosyncrasies — while bank, sell value and the chip flags were assigned scales of 10–30,
   i.e. flattened to near-irrelevance. The model itself reports that the features beyond
   remaining-weeks carried almost nothing it could use across seasons.
4. **The phase table agrees.** The GP is closest to the baseline early (114 vs 105, when
   everything is far away and both are guessing) and loses worst late (100 vs 61, when the
   baseline's per-week average is at its sharpest). A terminal value that is weakest
   exactly where a five-week plan needs it most would have been unusable even at parity.

## What this changes

- **The planner keeps the holding-value constants.** They were measured (+97..114 a
  season), they were the baseline here, and they won.
- **Phase 4's terminal-value line is not cancelled — its input is.** The state
  representation `(remaining weeks, bank, sell value, transfers, chips)` at season-chain
  grain does not price the future. Two representations that might are recorded here for
  whenever they earn a *new* pre-registration, not as a retry of this one:
  a target normalised to per-remaining-week net (removing the trivial length effect the
  baseline already owns), and features that describe the *squad itself* (projected points
  of the held eleven, fixture calendar ahead) rather than the wallet around it.
- **The three-week product windows never depended on this.** The GP was for season-scale
  planning; window pricing, modes, and the rival edge are untouched.

Measurement only: nothing consumed the fitted value before, nothing does now, and the
locked holdout was never read. 790 seconds, 2,860 rows, 80 chains, all committed inputs.
