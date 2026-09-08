# Rotation oracle ceiling (G0)

Contract `rotation_oracle_ceiling_v1`, generated 2026-09-08T18:27:31+00:00.
Development-only reading. Nothing here is promoted, pinned or deployed, and the
locked 2025-26 holdout was not loaded.

**Verdict:** `ceiling_at_or_above_threshold` — paired mean difference **+0.9660** points per decision against a threshold of 0.5, 90% interval [+0.0272, +1.6327] over 147/147 paired folds.

**Claim tested:** A perfect rotation signal would be worth at least min_mean_improvement points per decision as a default exclusion, on the development folds.

**Reading the interval.** The mean clears the 0.5 threshold but the interval does not: it runs from +0.0272 to +1.6327, so a ceiling below the threshold is not ruled out by this measurement. The interval excludes zero, which is a weaker statement than clearing the gate, and the pre-registered claim is about the mean rather than the bound. A ceiling this wide is a reason to treat the number as an order of magnitude, not as a target.

**Where the difference lives.** The oracle changes nothing in 93 of 147 decisions and the median difference is +0.0000, so the mean is carried by a minority of folds rather than by a broad shift. It is also not consistent across seasons: 2021-22 goes the other way.

**What it does not license:** Nothing about the signal this lane is building. G0 measures an oracle that reads the target gameweek's own minutes; a reachable signal is measured under G1 and G2. A ceiling above the threshold licenses continuing to look, not shipping anything, and a ceiling below it says no reachable signal can clear the gate as a default exclusion.

## Arms

| arm | mean realized squad points | zero-minute selected starters | autosub points |
| --- | --- | --- | --- |
| control (Ridge, no exclusion) | 58.6054 | 76 | 186.0 |
| oracle exclusion | 59.5714 | 27 | 75.0 |

W/T/L for the oracle arm: **35/93/19**; median difference +0.0000. The control started 53 flagged player(s) across the paired folds — the mechanism the exclusion removes.

### Per season

| season | mean paired difference |
| --- | --- |
| 2021-22 | -0.3784 |
| 2022-23 | +0.6389 |
| 2023-24 | +2.8919 |
| 2024-25 | +0.7027 |

## The oracle

`rested_regular_oracle_v1`: a player is flagged when he recorded zero minutes in the target gameweek **and** his shifted 6-gameweek appearance rate is exactly 1.0. Flagged rows: **1829** of 85019 eligible (103848 panel rows); of the 49731 eligible zero-minute rows, the rate rule keeps only the recent regulars.

Scored with official autosubs and vice-captain fallback (official_autosub_captain_v2) through evaluation.scoring.score_frozen_squad_decision. The season-chain path was rejected: it scores starters plus the captain again with no automatic substitutions, so removing the autosub rule that recovers points from a non-appearing starter would inflate the very gain this measurement is trying to bound.

**What that choice was worth.** Autosubs recover 1.27 points per decision for the control and only 0.51 for the oracle arm: excluding a rested regular removes the very non-appearance an autosub would have repaired. So the arm surrenders 0.76 points per decision of recovery to gain +0.9660 net. A scoring path with no automatic substitutions would not have charged that 0.76 back, and would have reported a ceiling near 1.72 — roughly 1.8 times the measured one. That is why the path is named in the record rather than left to the code.

The exclusion zeroes expected points after the projection and before the solve — the availability rule's own position and direction — and keeps every row, because dropping rows can turn a fold infeasible and would break the pairing.

## Limits a reader must know before quoting the number

- **oracle_reads_the_target_gameweek** — The flag uses the target gameweek's own minutes. That is what makes this a ceiling and it is what every feature in the repository is forbidden to do. A gameweek's own outcome may score a decision, never inform it; this measurement stands outside that rule by construction and produces no feature, column or model input.
- **playing_not_starting** — The development archive carries no verified start labels, so the appearance signal is minutes > 0. The oracle marks a recent regular who did not play at all, and cannot see a regular who started and was withdrawn early. It therefore flags fewer players than a start-aware oracle would, which makes the measured ceiling conservative in that direction.
- **no_availability_rule_in_either_arm** — Development folds carry no availability layer, so neither arm suppresses an injured or suspended player before the solve. The oracle therefore also catches absences a live availability rule already handles, which makes the measured ceiling generous in that direction: part of the gain is not rotation at all.
- **full_window_required** — A player needs all 6 prior gameweeks to be eligible. With the primitive's default of one prior observation a rate of 1.0 would mean 'played once', so the rule requires the whole window and a player without it is not eligible rather than being read as a regular.

## Reproducing this

Per-fold expansion: `artifacts/rotation/rotation_oracle_ceiling_folds.csv`, sha256 `37060f9426b4ef7c00ba84ae1c167dc09047b5aad1420609d4f0745954ba9722`. It sits in the evidence tier (ADR 0003) and is not committed; every number above is in the committed JSON beside this file, so the record is checkable without it.

Archive commit `8c97b2adb123863c3dd581e730f1360e89815ac2`, repository commit `88a8e2551d1c4b2a747b082b918e899861d5bb25`. Seasons loaded: 2020-21, 2021-22, 2022-23, 2023-24, 2024-25; decisions in 2021-22, 2022-23, 2023-24, 2024-25.

