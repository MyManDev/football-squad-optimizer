# Pre-registration: the value of a held free transfer on the component forecast

Status on the day this was frozen (27 Nov 2026): protocol fixed, no number of the measurement
seen. The record that fulfils it is `docs/research/component_banked_transfer_value.{json,md}`,
written by `scripts/measure_component_banked_transfer_value.py`; its row in the
[measurements index](../measurements_index.md) is the current state. Measurement only, nothing
promoted. Nothing in this document (arms, levels, gate, readings, seasons, budgets) changes
after any number of the measurement is seen.

## The question

The member planning policy (`MEMBER_PLANNING_POLICY` in `src/squadopt/live/transfers.py`,
`member_planning_policy_v2`) gives a free transfer carried into next week no value:
`banked_transfer_value_points` is 0. At one week ahead the planner therefore spends a free
transfer on any move its forecast scores above zero, however small, and a member who holds
one free transfer is told to use it almost every week.

The owner's question (26 Nov 2026): there should be a threshold under which no transfer is
advised, because a free transfer kept in hand has a value of its own. The knob that expresses
it exists. With a value `v`, the one-week solve adds `v` points for each free transfer carried
into the next week, so a free transfer is spent only on a move worth more than `v`, and at
the bank cap, where saving adds nothing, the threshold switches itself off
(`planning.optimizer`, `terminal_banked_transfer_value`).

It was last measured on the form-window control: [transfer discipline](../transfer_discipline_note.md)
crossed banked values {0, 1, 2} with hit costs and caps on the lookahead-1 chain and found a
banked value negative wherever its interval left zero. That forecast overstated what a
transfer brings (projected minus realized +33.9 a decision on
[the hit margin chain](component_hit_margin.md)), so a threshold there mostly blocked moves
that were not worth making anyway and the chain read the blocked hits, not the value of
holding. The squads a member is served are decided on the Phase C component base, whose
projected minus realized on the same chain is -1.1 a decision, and on which the planner
makes about one transfer a week and pays almost no hits. Whether a held free transfer is
worth anything on that forecast has not been measured.

So the question is: on the component base, under this season's rules, does a positive value
for a held free transfer beat the policy's 0, and at what level?

## What makes the measurement possible

`supplied_decision_week_v1` and `squadopt.experiments.component_chain`, added for
[the hit margin study](component_hit_margin_prereg.md), walk a season chain on the
component base's decision-week forecast, composed exactly as the component evaluation does.
Nothing is fitted. This study reuses both unchanged.

## Seasons, data and rules

- 2021-22, 2022-23, 2023-24 and 2024-25 from the pinned archive (`data/raw/vaastav-fpl`),
  each walked once as a chain from its first decision gameweek to its last, state carried.
  147 decisions in all (37, 36, 37, 37).
- The component forecast is the frozen handoff `phase_c_component_oof_v1` whose digests
  `docs/phase_c_component_evaluation.json` names; the runner refuses any other.
- 2025-26 is not read.
- **Two free-transfer rules.** The value of holding depends on how many can be held.
  - `rules_2026_27`, the primary: the bank cap is 5 in every season, the rule the member
    path plans under this season. Scoring does not depend on the cap, so the old seasons'
    points are a valid sheet for a planner that may hold five.
  - `season_rules`, secondary: each season's own cap (2, 2, 2, 5), as every earlier chain
    walked it.

## Arms

Every arm is the member policy as the hit margin study expressed it (planning hit cost 8,
the game's charge of 4 on the sheet, no discount, no transfer cap, chips off, sell-on fee
halved, lookahead 1, form window 5, candidate pools 20 and 8, no automatic substitution),
with one control moved: `banked_transfer_value_points`.

- Levels: **0, 0.5, 1, 1.5, 2, 3, 4, 6** points. 0 is the policy.
- Cells:
  - `component` under `rules_2026_27`, the primary;
  - `component` under `season_rules`;
  - the form-window `control` under `season_rules`, descriptive only, so the record can say
    whether the sign moved with the forecast.
- That is 3 cells × 8 levels × 4 seasons = 96 chains. One process per season and cell
  (twelve), each writing under `artifacts/component_banked_transfer_value/`; `--merge`
  writes the record.
- Solver: deterministic budget 8 a decision (the hit margin study's), wall ceiling 60 s.

## Comparisons

Within each cell, each level against 0, paired by gameweek: net points a week (realized minus
hits charged at 4). Season-aware moving-block bootstrap, block 4, 2,000 resamples, seed 0,
90% interval, as `season_chain_runs.chain_comparison` computes it.

## Gate

A level passes against 0 when all three hold:

1. the mean paired gain is at least **1.5 points a gameweek** (the noise floor);
2. the 90% interval is above zero;
3. the level's season net is lower than 0's in at most **one** of the four seasons.

## Readings, fixed now

Read on the primary cell, `component` under `rules_2026_27`:

- **`move`**: some level passes the gate. The candidate is the passing level with the highest
  pooled mean, the lower level on a tie. A move is a proposal to the owner to set
  `banked_transfer_value_points` in a new member policy version; this study changes no
  default.
- **`direction`**: no level passes, but some level has its 90% interval above zero and at most
  one losing season, with a mean under 1.5. The record names that level. It is evidence the
  owner may weigh, not a gate pass.
- **`unsupported`**: neither. The policy's 0 stands on this evidence.

Also named in every reading, deciding nothing by themselves:
- the level with the highest pooled mean, and whether it sits on the edge of the grid;
- every level whose 90% interval is below zero;
- the same reading computed on the secondary cell, and whether it agrees with the primary.

Seven levels are compared against one baseline on one population. The record says so beside
the reading; it does not correct the intervals.

## Described, not gated

Per chain and pooled by level:
- transfers made, free transfers used, paid transfers and hit points;
- free transfers lost: weeks that start at the bank cap and make no transfer;
- the mean free transfers held at the start of a week;
- the forecast's projected minus realized points a decision.

## What does not change

No default, no live path, no published file. The member policy keeps
`banked_transfer_value_points` = 0 until the owner decides on a `move` or `direction`
reading. Wiring a value into `MEMBER_PLANNING_POLICY` is its own PR, with the device solve's
parity fixture regenerated, because the device mirrors the server's objective.
