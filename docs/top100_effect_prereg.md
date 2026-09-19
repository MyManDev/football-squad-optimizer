# The Top 100 effect: protocol

Status: pre-registered on 2026-09-19, before any outcome of gameweek 5 of 2026-27 had been
captured or read; no reading under this protocol has been taken. This document changes no
projection, menu, price or live control, and it promotes nothing.

Correction, 2026-09-19: the first version of this line said "before gameweek 5 kicked
off". That was wrong. Gameweek 5's deadline was Friday 18 September 17:30Z and its first
match kicked off at 19:00Z; this protocol was merged on Saturday 19 September at 01:22Z,
with one of ten fixtures played and nine to come. What is true, and what matters for a
protocol, is that nothing of gameweek 5 had been read or could have been: the newest capture
on disk (`fpl-live-20260918T122516Z`) predates the deadline, so no gameweek 5 outcome existed
in the repository's data when this was written.

## Why this is written

Two things in production rest on the same unmeasured belief, that a player many of the Top 100
managers started is worth more than our projection says:

- the operational rule of `phase_c_operational_elite_policy.md`, which multiplies expected
  points by `1 + 0.05 * support` and reached production with no measurement of its own
  (`measurements_index.md` says so), and which the system's own decision has run without
  since gameweek 5 (`--projection component-only`);
- the member's menu (#594), which offers the same form at weights 5 to 50 and states, for each
  weight, what the choice costs on the base projection.

The menu is honest as it stands: it is a member's preference with a price, and it claims no
gain. What nobody can say today is whether the belief under it is true. This protocol fixes how
that will be read, and when, before there is anything to read.

## What is on disk, as of 2026-09-19

| Gameweek | Evidence export | Base projection (no uplift) | Weighted plans recorded | Realized |
| --- | --- | --- | --- | --- |
| 3 | yes (`player_evidence_v1_2026-27_gw03_top100`) | none from a pre-deadline capture | no | yes |
| 4 | yes | only as a replay: the control handoff was written two days after the deadline from a pre-deadline capture; the handoff that decided carried the uplift | no | yes |
| 5 | yes (`..._gw05_top100_efa7e3bfa351`, 100 of 100 members) | yes, the handoff that decided | published on the site, but the advice record of that capture predates #645 and does not hold them | not yet |
| 6 onwards | one per decision run | yes, while the run stays `component-only` | yes, in `member_advice_record_v2` | not yet |

So the player-level reading starts at gameweek 5 and the plan-level reading at gameweek 6.
Gameweek 4 may be shown beside the player-level table labelled `replay` and is never pooled.
Gameweek 5's weighted plans are left out of the plan-level reading; they are not rebuilt from
the published tree, because a reading whose input was assembled after the fact is a different
reading. A later gameweek joins a reading only if its export passed the handoff's own gate
(`apply_elite_evidence`) for the capture that decided and its base projection carries no
uplift (`projection_evidence_fingerprint` absent). A week that fails either is listed with the
reason and left out; it is not repaired.

## Reading one, player level: does the count say anything our projection does not

This is where the power is: several hundred player rows a week against fifteen members.

**Unit.** One player in one gameweek, for every player the decided base projection names.

**Quantities.** `m` is the decided projection (expected points times the capture's
availability multiplier, the same `ours_decided` column as `live_projection_audit`). `s` is
`elite_start_count_lag1 / 100` from that week's export; a player the export does not list has
`s = 0`, which is what the export means by absence. `y` is the realized `total_points` from a
later capture. The residual is `r = y - m`.

**Statistic A, on the rule's own scale.** The rule says the truth is `m * (1 + w * s)`, that
is `r = w * (m * s) + noise`. So the weight the data would choose is the slope of `r` on
`m * s`, with one intercept per gameweek and position so that a week or a position the
projection missed as a whole is not credited to the Top 100:

```text
w_hat = sum((x - mean_g(x)) * (r - mean_g(r))) / sum((x - mean_g(x))^2),  x = m * s,
g = (gameweek, position)
```

It reads directly against 0.05 (the operational rule) and against the menu's 0.05 to 0.50.

**Statistic B, with no functional form.** Within each gameweek and position, among the forty
players with the highest `m` (the same `TOP_PER_POSITION` as the live audit, chosen within the
week, never across weeks), the rank agreement between `s` and `r`. Reported per group and as
the mean over groups.

**The split that keeps the reading honest.** Both statistics are given three ways: all
players, players who appeared (`minutes > 0`), and the share of `sum(m * s)` that sat on
players who did not appear. Elite managers may simply know who plays. That is real information
too, but it is a different claim from knowing who scores, and the availability multiplier is
already meant to carry it.

**Interval.** A 90 percent bootstrap that resamples whole gameweeks, 2000 draws, seed fixed in
the script. With fewer than six gameweeks no interval is printed. With eight it is printed and
the record says in the same sentence that eight clusters make a rough interval.

**What is declared before looking.** I expect `w_hat` to be positive and small, below 0.10,
and most of it to vanish in the appeared-only split. The count follows price, form and secure
minutes, and the projection already sees the first two.

## Reading two, plan level: what the weighted plans did

**Unit.** One member, one weight, one gameweek, from the advice record of the capture that was
published last before the deadline. Both arms are in the record: the weighted plan and the
member's own weight-0 control of the same capture. Nobody has to have followed either.

**Score.** `score_recorded_advice` for both arms (the official automatic substitutions and
captaincy, the recorded chip, minus the recorded hit), so the two arms are scored by one
function on one basis. A pair in which either arm is not `scoring_complete` is left out and
counted.

**Statistic.** `d = realized(weighted) - realized(control)` per pair. Reported per weight: the
number of pairs, how many plans differed from the control at all, the mean of `d` over all
pairs and over the pairs that differed, and wins, ties and losses. Beside it, the published
price of the same pairs, so the realized difference stands next to what the site said the
choice would cost.

**Dependence, stated plainly.** Fifteen members share one projection, one export and one set
of matches, and the six weights of one member are nested plans. The effective sample is the
number of gameweeks. The interval therefore resamples gameweeks, exactly as above, and the
reading is direction only. It cannot show a gain of the size the menu prices (tenths of a
point a week) by gameweek 12 or by gameweek 20, and the record will say so rather than print a
small interval from 600 dependent pairs.

## When it is read

Twice, on dates fixed now: after gameweek 12 settles (eight gameweeks at the player level,
seven at the plan level) and after gameweek 20 settles. Not before, not between, and not
"once more" after. Each reading is a committed record with a row in `measurements_index.md`;
the second is a new record and leaves the first as it was.

## What each outcome means

Nothing here switches anything on or off by itself.

- `w_hat`'s interval above zero at gameweek 20, in the appeared-only split as well: the count
  carries information the projection lacks. The right home for it is a feature in the point
  model, through that lane's own gate (İbrahim's zone), not a multiplier bolted on after it.
  This reading is the reason to open that work, and no more than that.
- The interval above zero for all players but not for those who appeared: the information is
  about who plays. That goes to the appearance component, the same lane.
- The interval includes zero: the belief stays unmeasured. The menu stays what it is, a
  preference with a price, and the operational rule stays out of the system's decision. The
  member-facing copy does not change in any of the three cases; it claims no gain today and
  will not start to.
- The interval below zero: the record says so, and the owner decides whether a menu that
  tilts towards a measured loss should still be offered.

## What this protocol does not do

It fits nothing and tunes nothing; `w_hat` is a reading and never becomes the rule's weight.
It reads no member's behaviour, only recorded publications. It makes no statement a member
sees. It does not revisit the gameweeks that are lost (1 to 3) or assemble the gameweek 5
plans after the fact.

## Reproduction

`python -m scripts.measure_top100_effect --season 2026-27 --through-gameweek 12` (and `20`),
to be added in its own pull request before the first reading, with its arithmetic tested on
synthetic frames. It reads the exports, the handoffs, the advice records and the captures
through their existing readers, takes the data root as an argument, solves nothing and writes
`docs/top100_effect_gw12.json` and `.md`.
